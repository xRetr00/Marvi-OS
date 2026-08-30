<#
.SYNOPSIS
  Interactive and command-line console for cutting a signed Marvi OS release.

.DESCRIPTION
  With no version argument, displays the current product version and asks for
  the next one. The validated version is delegated to scripts/release.ps1,
  which owns the clean-main checks, version commit, signed tag, verification,
  and push.

.EXAMPLE
  .\scripts\release-console.ps1

.EXAMPLE
  .\scripts\release-console.ps1 -Version 0.6.5

.EXAMPLE
  .\scripts\release-console.ps1 -Version 0.6.5 -DryRun
#>
param(
  [string]$Version,
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$versionFile = Join-Path $root 'VERSION'
$releaseScript = Join-Path $PSScriptRoot 'release.ps1'

if (-not (Test-Path -LiteralPath $versionFile)) {
  throw "VERSION was not found at $versionFile."
}
if (-not (Test-Path -LiteralPath $releaseScript)) {
  throw "The signed release script was not found at $releaseScript."
}

$current = (Get-Content -LiteralPath $versionFile | Select-Object -First 1).Trim()

Write-Host ''
Write-Host '+------------------------------------------+' -ForegroundColor DarkGray
Write-Host '| MARVI OS / SIGNED RELEASE CONSOLE        |' -ForegroundColor Cyan
Write-Host '+------------------------------------------+' -ForegroundColor DarkGray
Write-Host "  current  $current" -ForegroundColor Gray
Write-Host '  channel  release' -ForegroundColor Gray
Write-Host '  signing  required' -ForegroundColor Gray
Write-Host ''

if (-not $Version) {
  $Version = (Read-Host '  target version (for example 0.6.5)').Trim()
}

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
  throw "Version must be plain SemVer (got '$Version'). Example: 0.6.5"
}
if ($current -notmatch '^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$') {
  throw "Current VERSION is not valid SemVer (got '$current')."
}

$currentStable = $current -replace '-.*$', ''
if ([version]$Version -le [version]$currentStable) {
  throw "Target version $Version must be newer than current version $current."
}

Write-Host "  plan     $current -> $Version" -ForegroundColor White
Write-Host "  tag      v$Version (signed + verified)" -ForegroundColor White

if ($DryRun) {
  Write-Host '  result   validation passed; no files, commits, tags, or remotes changed' -ForegroundColor Green
  exit 0
}

Write-Host '  result   handing off to the signed release pipeline' -ForegroundColor Cyan
Write-Host ''
& $releaseScript -Version $Version
if ($LASTEXITCODE -ne 0) {
  throw "The signed release pipeline exited with code $LASTEXITCODE."
}
