. (Join-Path $PSScriptRoot 'runtime-config.ps1')
$ErrorActionPreference = 'Stop'
$server = Get-MarviLiveKitExe
$bindHost = (Get-MarviRuntime).livekit.host
if (-not (Test-Path -LiteralPath $server)) {
    throw "LiveKit Server is missing. See docs/VOICE-RUNTIME.md."
}
& $server --dev --bind $bindHost

