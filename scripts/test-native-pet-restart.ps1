param(
    [string]$Executable = (Join-Path $PSScriptRoot '..\apps\desktop\dist\win-unpacked\Marvi-OS.exe'),
    [int]$WarmupSeconds = 8
)

$ErrorActionPreference = 'Stop'
$runRoot = Join-Path ([System.IO.Path]::GetTempPath()) "marvi-pet-restart-$([guid]::NewGuid().ToString('N'))"
$userData = Join-Path $runRoot 'chromium'
New-Item -ItemType Directory -Force -Path $runRoot, $userData | Out-Null
$preferences = @{ enabled = $true; displayId = $null; side = 'right'; scale = 0.5 } | ConvertTo-Json
[System.IO.File]::WriteAllText((Join-Path $runRoot 'pet.json'), "$preferences`n")
$process = Start-Process -FilePath (Resolve-Path -LiteralPath $Executable).Path `
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
    $first = Get-Process marvi-pet-host -ErrorAction Stop | Where-Object {
        $_.Path -like "$(Split-Path -Parent (Resolve-Path -LiteralPath $Executable).Path)*"
    } | Select-Object -First 1
    if (-not $first) { throw 'native pet host did not start' }

    Stop-Process -Id $first.Id -Force
    Start-Sleep -Seconds 3
    $replacement = Get-Process marvi-pet-host -ErrorAction Stop | Where-Object {
        $_.Path -like "$(Split-Path -Parent (Resolve-Path -LiteralPath $Executable).Path)*"
    } | Select-Object -First 1
    if (-not $replacement -or $replacement.Id -eq $first.Id) {
        throw 'native pet host was not restarted with a new process'
    }
    if (-not (Get-Process -Id $process.Id -ErrorAction SilentlyContinue)) {
        throw 'Marvi exited when the native pet host was terminated'
    }

    $result = [ordered]@{
        ok = $true
        MarviProcessId = $process.Id
        TerminatedPetHostId = $first.Id
        ReplacementPetHostId = $replacement.Id
        RestartDelaySeconds = 3
    }
    $evidenceDir = Join-Path $PSScriptRoot '..\output\evidence'
    New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null
    $json = $result | ConvertTo-Json
    [System.IO.File]::WriteAllText((Join-Path $evidenceDir 'pet-native-restart.json'), "$json`n")
    $json
}
finally {
    $rows = @(Get-CimInstance Win32_Process)
    $ids = [System.Collections.Generic.HashSet[int]]::new()
    [void]$ids.Add($process.Id)
    do {
        $before = $ids.Count
        foreach ($row in $rows) {
            if ($ids.Contains([int]$row.ParentProcessId)) { [void]$ids.Add([int]$row.ProcessId) }
        }
    } while ($ids.Count -ne $before)
    foreach ($targetId in @($ids)) {
        Stop-Process -Id $targetId -Force -ErrorAction SilentlyContinue
    }
}
