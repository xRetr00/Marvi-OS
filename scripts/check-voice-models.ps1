[CmdletBinding()]
param([switch]$SkipHashes)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$manifest = Get-Content (Join-Path $repoRoot 'config\voice-models.json') | ConvertFrom-Json
$modelRoot = Join-Path $env:LOCALAPPDATA 'Marvi-OS\models'
$sttDir = Join-Path $modelRoot "stt\nemotron-3.5\$($manifest.stt.subdirectory)"
$ttsDir = Join-Path $modelRoot 'tts\vibevoice-realtime-0.5b\model'
$voicesDir = Join-Path $modelRoot 'tts\vibevoice-realtime-0.5b\voices'

function Confirm-Files($base, $files, $label) {
    foreach ($property in $files.PSObject.Properties) {
        $path = Join-Path $base $property.Name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "$label missing $path" }
        $expectedBytes = [long]$property.Value[0]
        if ((Get-Item -LiteralPath $path).Length -ne $expectedBytes) { throw "$label size mismatch: $path" }
        if (-not $SkipHashes) {
            $expectedHash = [string]$property.Value[1]
            if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $expectedHash) {
                throw "$label SHA256 mismatch: $path"
            }
        }
    }
}

Confirm-Files $sttDir $manifest.stt.files 'STT'
Confirm-Files $ttsDir $manifest.tts.files 'TTS'
$voiceNames = @(Get-ChildItem -LiteralPath $voicesDir -Filter '*.pt' | ForEach-Object BaseName | Sort-Object)
if ($voiceNames.Count -lt 1) { throw "No VibeVoice presets found in $voicesDir" }
if ($voiceNames -notcontains $manifest.tts.default_voice) { throw 'Default TTS voice is missing.' }

[pscustomobject]@{
    STT = "ready ($($manifest.stt.language))"
    TTS = 'ready'
    Voices = $voiceNames.Count
    DefaultVoice = $manifest.tts.default_voice
    Hashes = -not $SkipHashes
} | Format-List
$voiceNames | ForEach-Object { "voice=$_" }

