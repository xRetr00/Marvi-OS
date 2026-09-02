# The Pipecat round, one engine at a time.
#
# Serial on purpose. The first attempt ran Nemotron while the Kyutai rerun was
# still going and both RTFs were meaningless: one 3060, two models, and a
# throughput number that describes the contention rather than the engine. Every
# latency figure in `docs/evals` was measured with the GPU to itself, so this
# one has to be too.
#
#   pwsh evals/pipecat_round.ps1

$ErrorActionPreference = "Stop"
$root = "C:\Users\xRetro\AppData\Local\Marvi-OS\evals\stt-candidates"
$corpus = "$root\corpus-pipecat"
$results = "$root\results"
$bin = "$root\runtimes\parakeet-cpp-v0.5.0\bin"
$py = "D:\Marvi-OS\.venv\Scripts\python.exe"

Set-Location "D:\Marvi-OS"

# The recogniser Marvi actually runs, not whatever the defaults fall back to.
#
# Both of these are read by `parakeet_stt` and both change which engine is
# measured. Without them the first run of this script quietly benchmarked the
# v3 multilingual model on the processor: `providers()` returns CPU unless
# `MARVI_STT_DEVICE` says cuda, and `chosen_model()` returns v3 unless the
# language is pinned to English. It transcribed beautifully and reported
# RTF 0.539 against the 0.055 in the EdAcc table -- two different models on two
# different devices, presented as the same row.
$env:MARVI_STT_DEVICE = "cuda"
$env:MARVI_STT_LANGUAGE = "en"

function Step($name, $block) {
    Write-Host "=== $name"
    $began = Get-Date
    & $block
    if ($LASTEXITCODE -ne 0) { Write-Host "!!! $name exited $LASTEXITCODE" }
    Write-Host ("--- {0} in {1:n0}s" -f $name, ((Get-Date) - $began).TotalSeconds)
}

Step "parakeet-tdt" {
    & $py evals\parakeet_tdt_runner.py "$corpus\manifest.jsonl" $corpus `
        "$results\parakeet-tdt-pipecat.jsonl" *> "$results\parakeet-tdt-pipecat.log"
}

Step "nemotron-3.5" {
    & $py evals\parakeet_cpp_runner.py nemotron "$corpus\manifest.jsonl" $corpus `
        "$root\models\parakeet-cpp\nemotron-3.5-asr-streaming-0.6b-f16.gguf" `
        "$bin\parakeet-v0.5.0-lib-win-cuda-x64\parakeet.dll" `
        "$bin\cudart-parakeet-bin-win-cuda-x64" `
        "$results\nemotron-pipecat.jsonl" *> "$results\nemotron-pipecat.log"
}

Step "whisper-large-v3-turbo" {
    # `--no-vac` for the same reason the EdAcc round used it: this venv has no
    # `onnxruntime`, so the voice-activity controller loads from TorchScript on
    # every clip and the run goes from minutes to hours.
    & "$root\runtimes\whisperlivekit\Scripts\python.exe" evals\whisperlivekit_runner.py `
        "$corpus\manifest.jsonl" $corpus `
        "$root\models\whisperlivekit-large-v3-turbo\encoder" `
        "$root\models\whisperlivekit-large-v3-turbo\decoder" `
        "$bin\cudart-parakeet-bin-win-cuda-x64" `
        "$results\whisper-pipecat.jsonl" --no-vac *> "$results\whisper-pipecat.log"
}

Step "kyutai-stt-1b" {
    & "$root\runtimes\kyutai-stt\Scripts\python.exe" evals\kyutai_stt_runner.py `
        "$corpus\manifest.jsonl" $corpus "$root\models\kyutai-stt-1b-en-fr" `
        "$results\kyutai-pipecat.jsonl" *> "$results\kyutai-pipecat.log"
}

Write-Host "=== scoring"
foreach ($name in @("parakeet-tdt", "nemotron", "whisper", "kyutai")) {
    $predictions = "$results\$name-pipecat.jsonl"
    if (-not (Test-Path $predictions)) { continue }
    & $py evals\stt_score.py "$corpus\manifest.jsonl" $predictions `
        --output "$results\$name-pipecat-score.json" *> $null
    & $py evals\semantic_wer.py "$corpus\manifest.jsonl" $predictions `
        --output "$results\$name-pipecat-semantic.json" *> "$results\$name-pipecat-semantic.log"
    Write-Host "scored $name"
}
