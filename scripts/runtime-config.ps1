# Reads config/runtime.json so the scripts and the desktop shell agree.
# The LiveKit version used to be written out in three files; changing one and
# forgetting the others is exactly how a launcher ends up pointing at a binary
# that is not there.
$ErrorActionPreference = 'Stop'

function Get-MarviRuntime {
    $repo = Split-Path $PSScriptRoot -Parent
    $path = Join-Path $repo 'config\runtime.json'
    if (-not (Test-Path -LiteralPath $path)) {
        throw "config/runtime.json is missing at $path"
    }
    Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
}

function Get-MarviLiveKitExe {
    if ($env:MARVI_LIVEKIT_SERVER) { return $env:MARVI_LIVEKIT_SERVER }
    $version = (Get-MarviRuntime).livekit.version
    Join-Path $env:LOCALAPPDATA "Marvi-OS\runtime\livekit\$version\livekit-server.exe"
}

function Get-MarviLiveKitUrl {
    if ($env:LIVEKIT_URL) { return $env:LIVEKIT_URL }
    $livekit = (Get-MarviRuntime).livekit
    "ws://$($livekit.host):$($livekit.port)"
}

function Get-MarviGatewayBind {
    $gateway = (Get-MarviRuntime).gateway
    @{ Host = $gateway.host; Port = $gateway.port }
}
