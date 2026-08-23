param(
    [string]$Executable = (Join-Path $PSScriptRoot '..\apps\desktop\dist\win-unpacked\Marvi-OS.exe'),
    [int]$WarmupSeconds = 10,
    [int]$SampleSeconds = 8
)

$ErrorActionPreference = 'Stop'
$resolvedExecutable = (Resolve-Path -LiteralPath $Executable).Path
$evidenceDir = Join-Path $PSScriptRoot '..\output\evidence'
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null

function Get-DescendantIds([int]$RootId) {
    $rows = @(Get-CimInstance Win32_Process)
    $found = [System.Collections.Generic.HashSet[int]]::new()
    [void]$found.Add($RootId)
    do {
        $before = $found.Count
        foreach ($row in $rows) {
            if ($found.Contains([int]$row.ParentProcessId)) {
                [void]$found.Add([int]$row.ProcessId)
            }
        }
    } while ($found.Count -ne $before)
    return @($found)
}

function Get-MarviProcesses([int]$RootId) {
    $ids = @(Get-DescendantIds $RootId)
    return @(Get-Process -Id $ids -ErrorAction SilentlyContinue)
}

function Measure-Mode([bool]$Enabled) {
    $label = if ($Enabled) { 'enabled' } else { 'disabled' }
    $runRoot = Join-Path ([System.IO.Path]::GetTempPath()) "marvi-pet-measure-$label-$([guid]::NewGuid().ToString('N'))"
    $userData = Join-Path $runRoot 'chromium'
    New-Item -ItemType Directory -Force -Path $runRoot, $userData | Out-Null
    $preferences = @{
        enabled = $Enabled
        displayId = $null
        side = 'right'
        scale = 0.5
    } | ConvertTo-Json
    [System.IO.File]::WriteAllText((Join-Path $runRoot 'pet.json'), "$preferences`n")

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
        $initialCpu = @{}
        foreach ($item in @(Get-MarviProcesses $process.Id)) {
            $initialCpu[$item.Id] = $item.CPU
        }

        $samples = @()
        $iterations = [Math]::Max(1, $SampleSeconds * 2)
        for ($index = 0; $index -lt $iterations; $index++) {
            $items = @(Get-MarviProcesses $process.Id)
            $petItems = @($items | Where-Object ProcessName -eq 'marvi-pet-host')
            $samples += [pscustomobject]@{
                ProcessCount = $items.Count
                WorkingSetBytes = ($items | Measure-Object WorkingSet64 -Sum).Sum
                PrivateBytes = ($items | Measure-Object PrivateMemorySize64 -Sum).Sum
                PetHostProcessCount = $petItems.Count
                PetHostWorkingSetBytes = (($petItems | Measure-Object WorkingSet64 -Sum).Sum ?? 0)
                PetHostPrivateBytes = (($petItems | Measure-Object PrivateMemorySize64 -Sum).Sum ?? 0)
            }
            Start-Sleep -Milliseconds 500
        }

        $finalProcesses = @(Get-MarviProcesses $process.Id)
        $cpuSeconds = 0.0
        $petHostCpuSeconds = 0.0
        foreach ($item in $finalProcesses) {
            $startCpu = if ($initialCpu.ContainsKey($item.Id)) { $initialCpu[$item.Id] } else { 0 }
            $itemCpuSeconds = [Math]::Max(0, $item.CPU - $startCpu)
            $cpuSeconds += $itemCpuSeconds
            if ($item.ProcessName -eq 'marvi-pet-host') { $petHostCpuSeconds += $itemCpuSeconds }
        }

        return [pscustomobject]@{
            Mode = $label
            ProcessCountAverage = [Math]::Round(($samples | Measure-Object ProcessCount -Average).Average, 2)
            WorkingSetMiBAverage = [Math]::Round(($samples | Measure-Object WorkingSetBytes -Average).Average / 1MB, 2)
            WorkingSetMiBPeak = [Math]::Round(($samples | Measure-Object WorkingSetBytes -Maximum).Maximum / 1MB, 2)
            PrivateMiBAverage = [Math]::Round(($samples | Measure-Object PrivateBytes -Average).Average / 1MB, 2)
            CpuPercentOneCore = [Math]::Round(($cpuSeconds / $SampleSeconds) * 100, 2)
            PetHostProcessCountAverage = [Math]::Round(($samples | Measure-Object PetHostProcessCount -Average).Average, 2)
            PetHostWorkingSetMiBAverage = [Math]::Round(($samples | Measure-Object PetHostWorkingSetBytes -Average).Average / 1MB, 2)
            PetHostPrivateMiBAverage = [Math]::Round(($samples | Measure-Object PetHostPrivateBytes -Average).Average / 1MB, 2)
            PetHostCpuPercentOneCore = [Math]::Round(($petHostCpuSeconds / $SampleSeconds) * 100, 2)
            StateDirectory = $runRoot
        }
    }
    finally {
        $ids = @(Get-DescendantIds $process.Id | Sort-Object -Descending)
        foreach ($id in $ids) {
            Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
        }
    }
}

$disabled = Measure-Mode $false
$enabled = Measure-Mode $true
$result = [ordered]@{
    RecordedAt = (Get-Date).ToString('o')
    Host = [ordered]@{
        Computer = $env:COMPUTERNAME
        OperatingSystem = (Get-CimInstance Win32_OperatingSystem).Caption
        Processor = (Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name).Trim()
        MemoryGiB = [Math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
        Electron = '43.4.0'
        Build = '0.4.15 win-unpacked + native pet host spike'
    }
    Conditions = [ordered]@{
        WarmupSeconds = $WarmupSeconds
        SampleSeconds = $SampleSeconds
        VoiceStackManaged = $false
        GatewayUrl = 'unreachable loopback'
        MainWindowVisible = $true
        IslandVisible = $true
    }
    Disabled = $disabled
    Enabled = $enabled
    Delta = [ordered]@{
        ProcessCountAverage = [Math]::Round($enabled.ProcessCountAverage - $disabled.ProcessCountAverage, 2)
        WorkingSetMiBAverage = [Math]::Round($enabled.WorkingSetMiBAverage - $disabled.WorkingSetMiBAverage, 2)
        WorkingSetMiBPeak = [Math]::Round($enabled.WorkingSetMiBPeak - $disabled.WorkingSetMiBPeak, 2)
        PrivateMiBAverage = [Math]::Round($enabled.PrivateMiBAverage - $disabled.PrivateMiBAverage, 2)
        CpuPercentOneCore = [Math]::Round($enabled.CpuPercentOneCore - $disabled.CpuPercentOneCore, 2)
    }
}

$outputPath = Join-Path $evidenceDir 'pet-resource-measurement.json'
$json = $result | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText($outputPath, "$json`n")
$json
