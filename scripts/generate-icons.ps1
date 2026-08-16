$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $repositoryRoot 'assets\app-icon-source.png'
$desktop = Join-Path $repositoryRoot 'apps\desktop'
$magick = Get-Command magick -ErrorAction Stop

New-Item -ItemType Directory -Force -Path (Join-Path $desktop 'build') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $desktop 'resources') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $desktop 'src\renderer\src\assets') | Out-Null

& $magick.Source $source -filter Lanczos -resize '512x512' (Join-Path $desktop 'build\icon.png')
& $magick.Source $source -define 'icon:auto-resize=256,128,64,48,32,24,16' (Join-Path $desktop 'build\icon.ico')
& $magick.Source $source -filter Lanczos -resize '256x256' (Join-Path $desktop 'resources\icon.png')
& $magick.Source $source -filter Lanczos -resize '32x32' (Join-Path $desktop 'resources\tray-icon.png')
& $magick.Source $source -filter Lanczos -resize '256x256' (Join-Path $desktop 'src\renderer\src\assets\app-icon.png')

Write-Host 'Generated Marvi OS desktop, renderer, tray, and Windows package icons.'
