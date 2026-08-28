$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $repositoryRoot 'assets\app-icon-source.png'
$desktop = Join-Path $repositoryRoot 'apps\desktop'
$updaterIcons = Join-Path $repositoryRoot 'apps\updater\src-tauri\icons'
$magick = Get-Command magick -ErrorAction Stop
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$temp = Join-Path $tempRoot ("marvi-icons-{0}" -f [Guid]::NewGuid().ToString('N'))

New-Item -ItemType Directory -Force -Path (Join-Path $desktop 'build') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $desktop 'resources') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $desktop 'src\renderer\src\assets') | Out-Null
New-Item -ItemType Directory -Force -Path $updaterIcons | Out-Null
New-Item -ItemType Directory -Force -Path $temp | Out-Null

function New-MarviPng {
  param(
    [Parameter(Mandatory = $true)][int]$Size,
    [Parameter(Mandatory = $true)][double]$Occupancy,
    [Parameter(Mandatory = $true)][string]$Output,
    [switch]$Small
  )

  $content = [Math]::Max(1, [Math]::Round($Size * $Occupancy))
  $arguments = @(
    $script:canonical,
    '-filter', 'Lanczos',
    '-resize', "${content}x${content}",
    '-gravity', 'center',
    '-background', 'none',
    '-extent', "${Size}x${Size}"
  )
  if ($Small) {
    # Low-resolution Windows surfaces need restrained edge recovery after
    # downsampling; otherwise the eye, hair highlights, and M seal collapse.
    $arguments += @('-unsharp', '0x0.55+0.55+0.015')
  }
  # Keep committed PNGs in explicit RGBA form at every size. ImageMagick may
  # otherwise palette-quantize tiny outputs, which makes alpha handling depend
  # on a separate tRNS chunk and has produced inconsistent Windows rendering.
  $arguments += "PNG32:$Output"
  & $magick.Source @arguments
  if ($LASTEXITCODE -ne 0) { throw "ImageMagick failed while writing $Output" }
}

try {
  $canonical = Join-Path $temp 'canonical.png'
  $script:canonical = $canonical

  # The repository artwork is slightly taller than it is wide. Pad it instead
  # of stretching it, then guarantee transparent rounded corners. Every
  # desktop/bootstrap derivative starts from this exact square master.
  & $magick.Source $source `
    -background none -gravity center -extent '%[fx:max(w,h)]x%[fx:max(w,h)]' `
    '(' +clone -alpha extract `
      -size '%[fx:w]x%[fx:h]' xc:none -fill white `
      -draw 'roundrectangle 0,0 %[fx:w-1],%[fx:h-1] %[fx:w*0.16],%[fx:h*0.16]' `
      -compose DstIn -composite ')' `
    -alpha off -compose CopyOpacity -composite $canonical
  if ($LASTEXITCODE -ne 0) { throw 'ImageMagick could not normalize the icon source.' }

  # Windows executable/taskbar and shortcut assets use a consistent 90% safe
  # area. The tray is purpose-sized and slightly tighter because Windows does
  # not add the same visual padding in the notification area.
  New-MarviPng 512 0.90 (Join-Path $desktop 'build\icon.png')
  New-MarviPng 256 0.90 (Join-Path $desktop 'resources\icon.png')
  New-MarviPng 32 0.96 (Join-Path $desktop 'resources\tray-icon.png') -Small
  New-MarviPng 256 1.00 (Join-Path $desktop 'src\renderer\src\assets\app-icon.png')

  $desktopIcoPngs = foreach ($size in 256, 128, 64, 48, 32, 24, 16) {
    $path = Join-Path $temp "desktop-$size.png"
    New-MarviPng $size 0.90 $path -Small:($size -le 64)
    $path
  }
  & $magick.Source @desktopIcoPngs (Join-Path $desktop 'build\icon.ico')
  & $magick.Source @desktopIcoPngs (Join-Path $desktop 'src\renderer\src\assets\app-icon.ico')

  $trayIcoPngs = foreach ($size in 32, 24, 20, 16) {
    $path = Join-Path $temp "tray-$size.png"
    New-MarviPng $size 0.96 $path -Small
    $path
  }
  & $magick.Source @trayIcoPngs (Join-Path $desktop 'resources\tray-icon.ico')

  New-MarviPng 128 0.90 (Join-Path $updaterIcons '128x128.png')
  New-MarviPng 32 0.90 (Join-Path $updaterIcons '32x32.png') -Small
  $bootstrapIcoPngs = foreach ($size in 256, 128, 64, 48, 32, 24, 16) {
    $path = Join-Path $temp "bootstrap-$size.png"
    New-MarviPng $size 0.90 $path -Small:($size -le 64)
    $path
  }
  & $magick.Source @bootstrapIcoPngs (Join-Path $updaterIcons 'icon.ico')

  Write-Host 'Generated rounded, purpose-sized Marvi OS desktop, renderer, tray, shortcut, and bootstrap icons.'
}
finally {
  $resolvedTemp = [IO.Path]::GetFullPath($temp)
  if ($resolvedTemp.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
    Remove-Item -LiteralPath $resolvedTemp -Recurse -Force -ErrorAction SilentlyContinue
  }
}
