# Cuts a Marvi OS release: bumps VERSION + package.json versions, commits,
# tags v<version>, and pushes. The tag push triggers the Release workflow.
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
if ((git rev-parse HEAD) -ne (git rev-parse origin/main)) {
  throw 'Local main is not in sync with origin/main. Pull or push first.'
}

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

Write-Host "Releasing $current -> $Version" -ForegroundColor Cyan

# VERSION is the single product version source; both package.json files mirror
# it so npm tooling and `app.getVersion()` agree (see AGENTS.md versioning).
Set-Content -Path VERSION -Value "$Version`n" -NoNewline
foreach ($pkg in @('package.json', 'apps\desktop\package.json')) {
  $json = Get-Content $pkg -Raw | ConvertFrom-Json
  $json.version = $Version
  $json | ConvertTo-Json -Depth 10 | Set-Content $pkg
}

git add VERSION package.json apps\desktop\package.json
git commit -m "chore: release $tag"
git tag -a $tag -m "Marvi OS $tag"
git push origin main
git push origin $tag

Write-Host @"

Pushed $tag. GitHub Actions now gates and publishes the release:
  https://github.com/xRetr00/Marvi-OS/actions?query=workflow%3ARelease
"@ -ForegroundColor Green
Pop-Location
