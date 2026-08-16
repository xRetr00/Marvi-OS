$ErrorActionPreference = 'Stop'
$server = Join-Path $env:LOCALAPPDATA 'Marvi-OS\runtime\livekit\1.13.5\livekit-server.exe'
if (-not (Test-Path -LiteralPath $server)) {
    throw "LiveKit Server is missing. See docs/VOICE-RUNTIME.md."
}
& $server --dev --bind 127.0.0.1

