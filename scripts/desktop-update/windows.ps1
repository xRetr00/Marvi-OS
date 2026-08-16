# windows.ps1 -- repository-owned Windows update hand-off for Marvi OS.
#
# WHY THIS LIVES IN THE REPO (adapted from D:\hermes-agent\scripts\desktop-
# update\windows.ps1, see docs/UPSTREAM.md): a frozen installer binary cannot
# fix its own updater. Every fix to the update path would then only reach users
# through a new signed installer, so update bugs outlive their fixes. Because
# this script is part of the checkout, each successful update also refreshes
# the code that drives the next one. Only PowerShell itself -- an OS component
# -- stays frozen.
#
# CONTRACT (keep in sync with apps/desktop/src/main/updater.ts):
#   cmd /d /s /c start "" /min powershell -NoProfile -ExecutionPolicy Bypass
#     -File scripts\desktop-update\windows.ps1
#     -InstallRoot <path>    the Marvi OS checkout to update
#     -Branch <ref>          branch to update against (default main)
#     -DesktopPid <pid>      Electron main process to wait out
#     [-RelaunchExe <path>]  executable to start when done
#     [-NoRelaunch]          skip relaunch (tests)
#
# The Electron side spawns this through a `cmd start` wrapper because a bare
# detached, hidden PowerShell is killed before -File is read.
#
# SAFETY POSTURE, in priority order:
#   1. A failed update must leave the previous installation working. The
#      pre-update commit is recorded first and restored on any build failure.
#   2. Preflight fails closed. If the desktop never exits, we abort without
#      touching the checkout -- a skipped update is recoverable, a half-applied
#      one is not.
#   3. Every exit path writes a result file, so the relaunched app can tell the
#      user what happened instead of silently appearing to have done nothing.
#   4. We always try to relaunch, so the user is never left with no app.

param(
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [string]$Branch = "main",
    [int]$DesktopPid = 0,
    [string]$RelaunchExe = "",
    [switch]$NoRelaunch
)

$ErrorActionPreference = "Continue"

$StateDir = Join-Path $env:LOCALAPPDATA "Marvi OS"
$MarkerPath = Join-Path $StateDir ".marvi-update-in-progress"
$ResultPath = Join-Path $StateDir ".marvi-update-result.json"
$LogPath = Join-Path $StateDir "update.log"

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

function Write-Log([string]$Message) {
    $line = "{0} {1}" -f (Get-Date -Format o), $Message
    try { Add-Content -Path $LogPath -Value $line -Encoding utf8 } catch { }
    Write-Host $line
}

function Write-Result([string]$Status, [string]$Message, [string]$From = "", [string]$To = "") {
    $payload = [ordered]@{
        status     = $Status
        message    = $Message
        from       = $From
        to         = $To
        branch     = $Branch
        finishedAt = (Get-Date -Format o)
    }
    try {
        # Windows PowerShell 5.1's -Encoding utf8 writes a BOM, and JSON.parse
        # on the Electron side rejects it. Write plain UTF-8 explicitly.
        $json = $payload | ConvertTo-Json -Depth 4
        [System.IO.File]::WriteAllText($ResultPath, $json, (New-Object System.Text.UTF8Encoding($false)))
    } catch {
        Write-Log "could not write result file: $_"
    }
}

function Remove-Marker {
    # Only clear a marker we still own. A handoff partner that rewrote it keeps
    # its own claim.
    if (-not (Test-Path $MarkerPath)) { return }
    try {
        $owner = (Get-Content -Path $MarkerPath -Raw -ErrorAction Stop).Trim()
        if ($owner -eq "$PID") { Remove-Item -Path $MarkerPath -Force -ErrorAction SilentlyContinue }
    } catch { }
}

function Start-Relaunch {
    if ($NoRelaunch -or -not $RelaunchExe) { return }
    if (-not (Test-Path $RelaunchExe)) {
        Write-Log "relaunch target missing: $RelaunchExe"
        return
    }
    try {
        Start-Process -FilePath $RelaunchExe -WorkingDirectory (Split-Path -Parent $RelaunchExe) | Out-Null
        Write-Log "relaunched $RelaunchExe"
    } catch {
        Write-Log "relaunch failed: $_"
    }
}

function Complete-Update([string]$Status, [string]$Message, [string]$From = "", [string]$To = "") {
    Write-Log "$Status`: $Message"
    Write-Result $Status $Message $From $To
    Remove-Marker
    Start-Relaunch
    if ($Status -eq "ok") { exit 0 } else { exit 1 }
}

# -- step 0: claim the marker ------------------------------------------------
[System.IO.File]::WriteAllText($MarkerPath, "$PID", (New-Object System.Text.UTF8Encoding($false)))
Write-Log "update started (pid $PID, branch $Branch, root $InstallRoot)"

# -- preflight: the checkout must be a usable git repo -----------------------
if (-not (Test-Path (Join-Path $InstallRoot ".git"))) {
    Complete-Update "failed" "No git checkout at $InstallRoot; cannot self-update."
}
Set-Location $InstallRoot

git rev-parse --is-inside-work-tree 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Complete-Update "failed" "Not a git work tree: $InstallRoot" }

$dirty = git status --porcelain
if ($dirty) {
    # Refusing here is the safe choice: overwriting local edits during an
    # unattended update is not recoverable for the user.
    Complete-Update "skipped" "Local changes present; update skipped to avoid discarding them."
}

# -- preflight: the app must actually exit (fails closed) --------------------
if ($DesktopPid -gt 0) {
    $waited = 0
    while ($waited -lt 60) {
        if (-not (Get-Process -Id $DesktopPid -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Seconds 1
        $waited++
    }
    if (Get-Process -Id $DesktopPid -ErrorAction SilentlyContinue) {
        Complete-Update "aborted" "Marvi OS did not exit within 60s; the installation was left untouched."
    }
    Write-Log "desktop pid $DesktopPid exited after ${waited}s"
}

# -- record the rollback point before touching anything ----------------------
$previous = (git rev-parse HEAD).Trim()
Write-Log "current commit $previous"

function Restore-Previous([string]$Reason) {
    Write-Log "restoring $previous ($Reason)"
    git reset --hard $previous 2>&1 | Out-Null
    Complete-Update "failed" "$Reason The previous version was restored." $previous $previous
}

# -- fetch and fast-forward --------------------------------------------------
git fetch --prune origin 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Complete-Update "failed" "Could not reach the update server." $previous $previous }

$target = (git rev-parse "origin/$Branch" 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $target) {
    Complete-Update "failed" "Branch origin/$Branch not found." $previous $previous
}
$target = $target.Trim()

if ($target -eq $previous) {
    Complete-Update "ok" "Already up to date." $previous $target
}

git merge --ff-only $target 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Restore-Previous "The update could not be applied cleanly."
}
Write-Log "moved to $target"

# -- rebuild -----------------------------------------------------------------
Write-Log "installing dependencies"
npm ci 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    npm install 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Restore-Previous "Dependency installation failed." }
}

Write-Log "building"
npm run build 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Restore-Previous "The build failed." }

Complete-Update "ok" "Updated successfully." $previous $target
