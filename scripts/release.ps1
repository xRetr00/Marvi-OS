# Cuts a Marvi OS release: synchronizes every product manifest and lockfile,
# commits, tags v<version>, and pushes. The tag push triggers the Release workflow.
#
# There is no per-release installer. The updater clones the tag and builds it
# on the machine, so the tag itself is the payload and the workflow publishes
# only the bootstrap binary and its checksum. What matters is that the tag
# builds: the workflow gates on the full test suite and on the exact build the
# updater will run.
#
#   .\scripts\release.ps1                 # first run: 0.1.0-dev.0 -> 0.1.0
#                                         # later: bumps patch (0.1.0 -> 0.1.1)
#   .\scripts\release.ps1 -Bump minor     # 0.1.0 -> 0.2.0
#   .\scripts\release.ps1 -Version 1.2.3  # explicit version
#
# Requires a clean working tree on main. Never edits anything else.
param(
  [string]$Version,
  [ValidateSet('patch', 'minor', 'major')]
  [string]$Bump = 'patch'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root

# Guard: clean tree, on main, in sync with origin.
$dirty = git status --porcelain
if ($dirty) { throw "Working tree is not clean. Commit or stash first.`n$dirty" }
$branch = git rev-parse --abbrev-ref HEAD
if ($branch -ne 'main') { throw "Release must be cut from main (currently on $branch)." }
git fetch origin
if ($LASTEXITCODE -ne 0) { throw 'Could not fetch origin.' }
$head = git rev-parse HEAD
$originHead = git rev-parse origin/main

$current = (Get-Content VERSION | Select-Object -First 1).Trim()

if (-not $Version) {
  if ($current -match '-') {
    # 0.1.0-dev.0 -> 0.1.0 : the first stable cut strips the prerelease.
    $Version = $current -replace '-.*$', ''
  } else {
    [int]$maj, [int]$min, [int]$pat = $current.Split('.')
    switch ($Bump) {
      'major' { $maj++; $min = 0; $pat = 0 }
      'minor' { $min++; $pat = 0 }
      'patch' { $pat++ }
    }
    $Version = "$maj.$min.$pat"
  }
}

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
  throw "Version must be plain SemVer (got '$Version'). Prereleases are not released through this script."
}

$tag = "v$Version"
if (git rev-parse -q --verify "refs/tags/$tag") {
  throw "Tag $tag already exists."
}

# A signing failure can happen after the release commit but before its push.
# Permit exactly that one clean, named local commit on retry; reject every
# other divergence so unrelated work cannot accidentally enter a release.
if ($head -ne $originHead) {
  git merge-base --is-ancestor origin/main HEAD
  $ahead = if ($LASTEXITCODE -eq 0) { [int](git rev-list --count origin/main..HEAD) } else { 0 }
  $subject = git log -1 --pretty=%s
  if ($current -ne $Version -or $ahead -ne 1 -or $subject -ne "chore: release $tag") {
    throw 'Local main is not in sync with origin/main and is not a retryable release commit.'
  }
  Write-Host "Retrying the unpushed $tag release commit." -ForegroundColor Yellow
}

# Validate signing before touching version files. Previously this guard ran
# after the commit, leaving a clean but unpushed release commit that the script
# itself refused to retry.
$signingKey = git config --get user.signingkey
if (-not $signingKey) {
  throw "No user.signingkey configured. A release tag must be signed; set it and retry."
}

Write-Host "Releasing $current -> $Version" -ForegroundColor Cyan

# One implementation owns every mirror: npm manifests and lock metadata,
# Python service projects and uv locks, native app Cargo manifests and locks,
# plus both Cargo and Tauri metadata for the self-updating bootstrap.
node --test scripts/sync-version.test.mjs
if ($LASTEXITCODE -ne 0) { throw 'Version synchronizer tests failed; no release files were changed.' }
node scripts/sync-version.mjs $Version
if ($LASTEXITCODE -ne 0) { throw "Could not synchronize product version $Version." }
node scripts/sync-version.mjs --check $Version
if ($LASTEXITCODE -ne 0) { throw "Product version $Version is still inconsistent after synchronization." }

# The tree was clean immediately before synchronization. Refuse to absorb a
# concurrent, unrelated edit into the release commit.
$versionFiles = @(git diff --name-only)
$allowedVersionFile = '^(VERSION|package\.json|package-lock\.json|uv\.lock|apps/desktop/package\.json|apps/[^/]+/(Cargo\.toml|Cargo\.lock)|apps/updater/src-tauri/tauri\.conf\.json|services/[^/]+/(pyproject\.toml|uv\.lock))$'
$unexpected = @($versionFiles | Where-Object { $_ -notmatch $allowedVersionFile })
if ($unexpected) {
  throw "Unexpected files changed while synchronizing the release:`n$($unexpected -join "`n")"
}
if ($versionFiles) { git add -- $versionFiles }
if ($LASTEXITCODE -ne 0) { throw 'Could not stage the version files.' }

# PowerShell's $ErrorActionPreference does not stop on a native command's exit
# code, so a `git commit` that failed was ignored and the script went on to tag
# and push whatever HEAD happened to be. That is how v0.5.0 came to point at a
# commit whose VERSION file said 0.4.15: another session started a merge
# mid-release, the commit failed on the conflict, and nothing noticed. CI's
# tag/VERSION guard caught it, which is the only reason it was not published.
$staged = git diff --cached --name-only
if ($staged) {
  git commit -m "chore: release $tag"
  if ($LASTEXITCODE -ne 0) { throw "Could not commit the version bump; $tag was not created." }
} else {
  # Every version file already says $Version. That happens on a retry after a
  # later step failed, and it means HEAD is already the release: there is
  # nothing to record, so tag what is there rather than inventing a commit.
  Write-Host "Version files already at $Version; tagging HEAD." -ForegroundColor Yellow
}
<#
.SYNOPSIS
  Run `git tag -s` with the signing passphrase supplied non-interactively.

.DESCRIPTION
  Git signs SSH tags by shelling out to `ssh-keygen -Y sign`, which needs the
  key's passphrase. There is no environment variable git or ssh-keygen reads a
  passphrase from -- by design. The one channel OpenSSH does accept one on is
  SSH_ASKPASS: a program it runs to ask. With SSH_ASKPASS_REQUIRE=force it uses
  that instead of the terminal, which is what makes an unattended release
  possible.

  ssh-agent would also work and is the more usual answer, but it is a Windows
  service that is disabled on a default install and enabling it needs an
  administrator. Askpass needs nothing but a temp file, so that is the path.

  The passphrase comes from `.release.env` at the repo root:

      MARVI_SIGNING_PASSPHRASE=...

  That file is gitignored and must stay that way -- it is a private key's
  passphrase in plaintext, which is a real trade: an unattended release for a
  secret that is only as safe as the disk. Without the file this falls back to
  a plain `git tag -s`, which prompts exactly as it always did.
#>
function Invoke-SignedTag {
  param([string] $Tag, [string] $Message)

  $passphrase = $null
  $envFile = Join-Path $root '.release.env'
  if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
      if ($line -match '^\s*MARVI_SIGNING_PASSPHRASE\s*=\s*(.+?)\s*$') {
        $passphrase = $Matches[1].Trim('"').Trim("'")
      }
    }
  }

  if (-not $passphrase) {
    Write-Host "No passphrase in .release.env; git will prompt." -ForegroundColor Yellow
    git tag -s $Tag -m $Message
    return
  }

  # A throwaway askpass helper. In a temp file rather than the repo so a stray
  # copy cannot be committed, and removed in `finally` so it does not outlive
  # the one command that needs it. It echoes an environment variable rather
  # than embedding the secret, so the passphrase is never written to disk.
  $askpass = Join-Path ([System.IO.Path]::GetTempPath()) "marvi-askpass-$([guid]::NewGuid()).cmd"
  try {
    Set-Content -Path $askpass -Value "@echo off`r`necho %MARVI_SIGNING_PASSPHRASE%" -Encoding ASCII
    $env:MARVI_SIGNING_PASSPHRASE = $passphrase
    $env:SSH_ASKPASS = $askpass
    # Without `force`, OpenSSH consults SSH_ASKPASS only when there is no
    # terminal -- and this script has one, so it would prompt anyway.
    $env:SSH_ASKPASS_REQUIRE = 'force'
    $env:DISPLAY = 'required-by-openssh'
    git tag -s $Tag -m $Message
  } finally {
    Remove-Item $askpass -ErrorAction SilentlyContinue
    Remove-Item Env:MARVI_SIGNING_PASSPHRASE -ErrorAction SilentlyContinue
    Remove-Item Env:SSH_ASKPASS -ErrorAction SilentlyContinue
    Remove-Item Env:SSH_ASKPASS_REQUIRE -ErrorAction SilentlyContinue
    Remove-Item Env:DISPLAY -ErrorAction SilentlyContinue
  }
}

# Signed, and explicitly rather than relying on tag.gpgsign being set on
# whichever machine cuts the release. Every tag before v0.3.3 was unsigned:
# commit.gpgsign was true and tag.gpgsign was not, and `git tag -a` does not
# sign. The updater treats an unsigned release tag as a warning, so nothing
# broke — it just never verified anything either.
Invoke-SignedTag $tag "Marvi OS $tag"
if ($LASTEXITCODE -ne 0) { throw "Signing $tag failed. The tag was not created." }

# Verified here, where a failure is cheap, rather than on a user's machine
# during an update.
$env:GIT_CONFIG_COUNT = "1"
$env:GIT_CONFIG_KEY_0 = "gpg.ssh.allowedSignersFile"
$env:GIT_CONFIG_VALUE_0 = ".github/allowed_signers"
git verify-tag $tag
if ($LASTEXITCODE -ne 0) {
  git tag -d $tag | Out-Null
  throw "$tag signed but did not verify against .github/allowed_signers. Tag removed."
}
Write-Host "Signed and verified $tag" -ForegroundColor Green
git push origin main
if ($LASTEXITCODE -ne 0) {
  git tag -d $tag | Out-Null
  throw "Could not push the $tag release commit. Local tag removed so the release can be retried."
}
git push origin $tag
if ($LASTEXITCODE -ne 0) {
  git tag -d $tag | Out-Null
  throw "Could not push $tag. Local tag removed so the release can be retried."
}

Write-Host @"

Pushed $tag. GitHub Actions now gates and publishes the release:
  https://github.com/xRetr00/Marvi-OS/actions?query=workflow%3ARelease
"@ -ForegroundColor Green
Pop-Location
