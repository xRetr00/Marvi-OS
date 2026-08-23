param(
    [string]$Executable = (Join-Path $PSScriptRoot '..\apps\desktop\dist\win-unpacked\Marvi-OS.exe'),
    [int]$WarmupSeconds = 10
)

$ErrorActionPreference = 'Stop'
$runRoot = Join-Path ([System.IO.Path]::GetTempPath()) "marvi-pet-visual-$([guid]::NewGuid().ToString('N'))"
$userData = Join-Path $runRoot 'chromium'
New-Item -ItemType Directory -Force -Path $runRoot, $userData | Out-Null
$preferences = @{ enabled = $true; displayId = $null; side = 'right'; scale = 0.5 } | ConvertTo-Json
[System.IO.File]::WriteAllText((Join-Path $runRoot 'pet.json'), "$preferences`n")
$resolvedExecutable = (Resolve-Path -LiteralPath $Executable).Path
$process = Start-Process -FilePath $resolvedExecutable `
    -ArgumentList "--user-data-dir=$userData" `
    -Environment @{
        MARVI_HOME = $runRoot
        MARVI_LOG_DIR = (Join-Path $runRoot 'logs')
        MARVI_MANAGE_VOICE_STACK = '0'
        MARVI_GATEWAY_URL = 'http://127.0.0.1:65530'
    } `
    -PassThru -WindowStyle Hidden

try {
    Start-Sleep -Seconds $WarmupSeconds
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class MarviPetWindow {
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr window, out RECT rect);
}
'@
    $bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
    $evidenceDir = Join-Path $PSScriptRoot '..\output\evidence'
    New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null

    function Save-Screen([string]$Path) {
        $bitmap = [System.Drawing.Bitmap]::new($bounds.Width, $bounds.Height)
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        try {
            $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
            $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
        }
        finally {
            $graphics.Dispose()
            $bitmap.Dispose()
        }
    }

    $idlePath = Join-Path $evidenceDir 'pet-native-status-idle.png'
    Save-Screen $idlePath

    $pet = Get-Process marvi-pet-host -ErrorAction Stop | Where-Object {
        $_.Path -like "$(Split-Path -Parent $resolvedExecutable)*"
    } | Select-Object -First 1
    if (-not $pet -or $pet.MainWindowHandle -eq 0) { throw 'native pet window was not found' }
    $rect = [MarviPetWindow+RECT]::new()
    if (-not [MarviPetWindow]::GetWindowRect($pet.MainWindowHandle, [ref]$rect)) {
        throw 'native pet window bounds were unavailable'
    }
    $originalCursor = [System.Windows.Forms.Cursor]::Position
    try {
        [System.Windows.Forms.Cursor]::Position = [System.Drawing.Point]::new(
            [int](($rect.Left + $rect.Right) / 2),
            $rect.Bottom - 16
        )
        Start-Sleep -Milliseconds 700
        $hoverPath = Join-Path $evidenceDir 'pet-native-controls-hover.png'
        Save-Screen $hoverPath
    }
    finally {
        [System.Windows.Forms.Cursor]::Position = $originalCursor
    }

    [ordered]@{
        Idle = (Resolve-Path -LiteralPath $idlePath).Path
        Hover = (Resolve-Path -LiteralPath $hoverPath).Path
    } | ConvertTo-Json
}
finally {
    $rows = @(Get-CimInstance Win32_Process)
    $ids = [System.Collections.Generic.HashSet[int]]::new()
    [void]$ids.Add($process.Id)
    do {
        $before = $ids.Count
        foreach ($row in $rows) {
            if ($ids.Contains([int]$row.ParentProcessId)) {
                [void]$ids.Add([int]$row.ProcessId)
            }
        }
    } while ($ids.Count -ne $before)
    foreach ($targetId in @($ids)) {
        Stop-Process -Id $targetId -Force -ErrorAction SilentlyContinue
    }
}
