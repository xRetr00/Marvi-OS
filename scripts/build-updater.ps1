# Builds the Marvi Bootstrap binary (the small installer + updater) for Windows.
#
#   .\scripts\build-updater.ps1              # tests + release build
#   .\scripts\build-updater.ps1 -SkipTests   # faster iteration
#
# Produces apps\updater\target\release\marvi-bootstrap.exe. The window UI is
# embedded at compile time, so the result is a single small executable (~a few
# MB) rather than a bundled installer.
param(
  [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$updater = Join-Path $root 'apps\updater'
Push-Location $updater

if (-not $SkipTests) {
  Write-Host "==> Bootstrap core tests" -ForegroundColor Cyan
  cargo test -p marvi-bootstrap-core
  if ($LASTEXITCODE -ne 0) { throw 'cargo test failed' }
}

Write-Host "==> Bootstrap release build" -ForegroundColor Cyan
cargo build --release -p marvi-bootstrap
if ($LASTEXITCODE -ne 0) { throw 'cargo build failed' }

$exe = Join-Path $updater 'target\release\marvi-bootstrap.exe'
if (-not (Test-Path $exe)) { throw "bootstrap binary not produced at $exe" }
$sizeMB = [math]::Round((Get-Item $exe).Length / 1MB, 2)
Write-Host "Built $exe ($sizeMB MB)" -ForegroundColor Green
Pop-Location
