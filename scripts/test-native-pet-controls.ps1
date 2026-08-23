param(
    [string]$Executable = (Join-Path $PSScriptRoot '..\apps\desktop\dist\win-unpacked\Marvi-OS.exe'),
    [int]$WarmupSeconds = 8
)

$ErrorActionPreference = 'Stop'
$runRoot = Join-Path ([System.IO.Path]::GetTempPath()) "marvi-pet-controls-$([guid]::NewGuid().ToString('N'))"
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

Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class MarviPetInput {
    public delegate bool EnumWindowsCallback(IntPtr window, IntPtr state);
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr window, out RECT rect);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsCallback callback, IntPtr state);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr window, int command);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);
    public static IntPtr FindLargestWindow(uint[] processIds) {
        IntPtr largest = IntPtr.Zero;
        long largestArea = 0;
        EnumWindows((window, state) => {
            uint processId;
            GetWindowThreadProcessId(window, out processId);
            if (Array.IndexOf(processIds, processId) < 0 || !IsWindowVisible(window)) return true;
            RECT rect;
            if (!GetWindowRect(window, out rect)) return true;
            long area = (long)(rect.Right - rect.Left) * (rect.Bottom - rect.Top);
            if (area > largestArea) { largestArea = area; largest = window; }
            return true;
        }, IntPtr.Zero);
        return largest;
    }
}
'@

function Get-DescendantIds([int]$RootId) {
    $rows = @(Get-CimInstance Win32_Process)
    $found = [System.Collections.Generic.HashSet[int]]::new()
    [void]$found.Add($RootId)
    do {
        $before = $found.Count
        foreach ($row in $rows) {
            if ($found.Contains([int]$row.ParentProcessId)) { [void]$found.Add([int]$row.ProcessId) }
        }
    } while ($found.Count -ne $before)
    return @($found)
}

try {
    Start-Sleep -Seconds $WarmupSeconds
    $pet = Get-Process -Id (Get-DescendantIds $process.Id) -ErrorAction SilentlyContinue |
        Where-Object ProcessName -eq 'marvi-pet-host' |
        Select-Object -First 1
    if (-not $pet -or $pet.MainWindowHandle -eq 0) { throw 'native pet window was not found' }
    $rect = [MarviPetInput+RECT]::new()
    if (-not [MarviPetInput]::GetWindowRect($pet.MainWindowHandle, [ref]$rect)) {
        throw 'native pet window bounds were unavailable'
    }
    $width = $rect.Right - $rect.Left
    $height = $rect.Bottom - $rect.Top
    $spriteHeight = [Math]::Round($width * 208 / 192)
    $radius = [Math]::Min(14, [Math]::Max(8, [Math]::Floor($width / 9)))
    $taskX = $rect.Left + [Math]::Floor($width / 2) + $radius + 4
    $controlY = $rect.Top + $spriteHeight + [Math]::Floor(($height - $spriteHeight) / 2)
    [uint32[]]$desktopIds = @(Get-DescendantIds $process.Id | Where-Object { $_ -ne $pet.Id })
    $mainWindow = [MarviPetInput]::FindLargestWindow($desktopIds)
    $mainRect = [MarviPetInput+RECT]::new()
    if ($mainWindow -ne [IntPtr]::Zero -and
        [MarviPetInput]::GetWindowRect($mainWindow, [ref]$mainRect) -and
        ($mainRect.Right - $mainRect.Left) -ge 900) {
        [void][MarviPetInput]::SendMessage($mainWindow, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
        Start-Sleep -Milliseconds 500
        if ([MarviPetInput]::IsWindowVisible($mainWindow)) {
            throw 'control center did not hide before testing the pet action'
        }
    }
    $originalCursor = [System.Windows.Forms.Cursor]::Position
    [System.Windows.Forms.Cursor]::Position = [System.Drawing.Point]::new($taskX, $controlY)
    Start-Sleep -Milliseconds 500
    $clientX = $taskX - $rect.Left
    $clientY = $controlY - $rect.Top
    $mousePosition = [IntPtr]::new(($clientY -shl 16) -bor ($clientX -band 0xffff))
    [void][MarviPetInput]::SendMessage(
        $pet.MainWindowHandle,
        0x0202,
        [IntPtr]::Zero,
        $mousePosition
    )
    Start-Sleep -Seconds 1

    [uint32[]]$currentDescendantIds = @(
        Get-DescendantIds $process.Id | Where-Object { $_ -ne $pet.Id }
    )
    $revealedWindow = [MarviPetInput]::FindLargestWindow($currentDescendantIds)
    $revealedRect = [MarviPetInput+RECT]::new()
    $revealed = $revealedWindow -ne [IntPtr]::Zero -and
        [MarviPetInput]::GetWindowRect($revealedWindow, [ref]$revealedRect) -and
        ($revealedRect.Right - $revealedRect.Left) -ge 900
    if (-not $revealed) {
        throw "task control did not reveal the Marvi control center (host=$($rect.Left),$($rect.Top),$width,$height; client=$clientX,$clientY)"
    }
    [uint32]$mainProcessId = 0
    [void][MarviPetInput]::GetWindowThreadProcessId($revealedWindow, [ref]$mainProcessId)
    $revealedProcess = Get-Process -Id $mainProcessId

    $result = [ordered]@{
        ok = $true
        Action = 'tasks'
        PetHostProcessId = $pet.Id
        MainWindowProcessId = $revealedProcess.Id
        MainWindowTitle = $revealedProcess.MainWindowTitle
    }
    $evidenceDir = Join-Path $PSScriptRoot '..\output\evidence'
    New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null
    $json = $result | ConvertTo-Json
    [System.IO.File]::WriteAllText((Join-Path $evidenceDir 'pet-native-controls.json'), "$json`n")
    $json
}
finally {
    if ($originalCursor) { [System.Windows.Forms.Cursor]::Position = $originalCursor }
    foreach ($targetId in @(Get-DescendantIds $process.Id | Sort-Object -Descending)) {
        Stop-Process -Id $targetId -Force -ErrorAction SilentlyContinue
    }
}
