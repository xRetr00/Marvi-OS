param(
    [string]$Executable = (Join-Path $PSScriptRoot '..\apps\desktop\dist\win-unpacked\Marvi-OS.exe'),
    [int]$WarmupSeconds = 10
)

$ErrorActionPreference = 'Stop'
$runRoot = Join-Path ([System.IO.Path]::GetTempPath()) "marvi-pet-visual-$([guid]::NewGuid().ToString('N'))"
$userData = Join-Path $runRoot 'chromium'
New-Item -ItemType Directory -Force -Path $runRoot, $userData | Out-Null
$preferences = @{ enabled = $true; displayId = $null; side = 'right'; scale = 1 } | ConvertTo-Json
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
    $bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
    $bitmap = [System.Drawing.Bitmap]::new($bounds.Width, $bounds.Height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
    $evidenceDir = Join-Path $PSScriptRoot '..\output\evidence'
    New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null
    $outputPath = Join-Path $evidenceDir 'pet-native.png'
    $bitmap.Save($outputPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose()
    $bitmap.Dispose()
    (Resolve-Path -LiteralPath $outputPath).Path
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
