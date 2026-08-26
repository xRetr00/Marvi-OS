# Builds the Marvi OS desktop app for Windows from a clean, verified state.
#
#   .\scripts\build-desktop.ps1              # full gate + installer
#   .\scripts\build-desktop.ps1 -SkipTests   # faster iteration builds
#
# Runs the same gates CI runs (typecheck, tests), then electron-vite build and
# electron-builder --win. Artifacts land in apps/desktop/dist/. Publish is
# always "never" here — releases happen only through tags + the Release
# workflow (see docs/DECISIONS.md ADR-016).
param(
  [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root

function Step([string]$name) { Write-Host "`n==> $name" -ForegroundColor Cyan }

Step "Environment"
$env:MARVI_BUILD_COMMIT = (git rev-parse --short HEAD)
$env:MARVI_BUILD_TIME = (Get-Date).ToUniversalTime().ToString('o')
Write-Host "commit=$env:MARVI_BUILD_COMMIT buildTime=$env:MARVI_BUILD_TIME version=$(Get-Content VERSION)"

if (-not (Test-Path node_modules)) {
  Step "npm install (first run)"
  npm install
  if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
}

Step "Typecheck"
npm run typecheck
if ($LASTEXITCODE -ne 0) { throw 'typecheck failed' }

if (-not $SkipTests) {
  Step "Tests"
  npm test
  if ($LASTEXITCODE -ne 0) { throw 'tests failed' }
}

Step "Renderer + main build"
npm run build
if ($LASTEXITCODE -ne 0) { throw 'electron-vite build failed' }

Step "Windows installer (electron-builder)"
npm run build:win
if ($LASTEXITCODE -ne 0) { throw 'electron-builder failed' }

Step "Artifacts"
Get-ChildItem apps\desktop\dist -File |
  Select-Object Name, @{ n = 'SizeMB'; e = { [math]::Round($_.Length / 1MB, 1) } } |
  Format-Table -AutoSize | Out-String | Write-Host

Write-Host "Done. Installer: apps\desktop\dist\" -ForegroundColor Green
Pop-Location
