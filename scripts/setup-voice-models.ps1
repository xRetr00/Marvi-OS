[CmdletBinding()]
param([switch]$SkipHashes)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$manifest = Get-Content (Join-Path $repoRoot 'config\voice-models.json') | ConvertFrom-Json
$modelRoot = Join-Path $env:LOCALAPPDATA 'Marvi-OS\models'
$sttRoot = Join-Path $modelRoot 'stt\nemotron-3.5'
$ttsRoot = Join-Path $modelRoot 'tts\vibevoice-realtime-0.5b'
$sttDir = Join-Path $sttRoot $manifest.stt.subdirectory
$ttsModel = Join-Path $ttsRoot 'model'
$voices = Join-Path $ttsRoot 'voices'

if (-not (Get-Command hf -ErrorAction SilentlyContinue)) {
    throw 'Hugging Face CLI is required. Install it with: uv tool install huggingface_hub'
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git is required.' }

New-Item -ItemType Directory -Force -Path $sttRoot, $ttsModel, $voices | Out-Null
hf download $manifest.stt.id --revision $manifest.stt.revision `
    --include "$($manifest.stt.subdirectory)/*" --local-dir $sttRoot
hf download $manifest.tts.id --revision $manifest.tts.revision --local-dir $ttsModel

$sourceDir = Join-Path ([IO.Path]::GetTempPath()) "marvi-vibevoice-$($manifest.tts.source_revision)"
if (-not (Test-Path $sourceDir)) {
    git clone --filter=blob:none --no-checkout https://github.com/microsoft/VibeVoice.git $sourceDir
    git -C $sourceDir checkout $manifest.tts.source_revision -- demo/voices/streaming_model
}
Copy-Item (Join-Path $sourceDir 'demo\voices\streaming_model\*.pt') $voices -Force

& (Join-Path $PSScriptRoot 'check-voice-models.ps1') -SkipHashes:$SkipHashes

