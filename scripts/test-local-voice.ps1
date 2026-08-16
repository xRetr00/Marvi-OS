. (Join-Path $PSScriptRoot 'runtime-config.ps1')
. (Join-Path $PSScriptRoot 'runtime-config.ps1')
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$logDir = Join-Path $env:LOCALAPPDATA 'Marvi-OS\logs'
$livekitExe = Get-MarviLiveKitExe
$uv = (Get-Command uv).Source
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$env:LIVEKIT_URL = Get-MarviLiveKitUrl
$env:LIVEKIT_API_KEY = 'devkey'
$env:LIVEKIT_API_SECRET = 'secret'
$env:OPENCODE_GO_API_KEY = 'transport-test-only'

$livekit = Start-Process -FilePath $livekitExe -ArgumentList @('--dev', '--bind', '127.0.0.1') `
    -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'livekit-test.log') `
    -RedirectStandardError (Join-Path $logDir 'livekit-test.err.log') -PassThru
$gateway = Start-Process -FilePath $uv `
    -ArgumentList @('run', '--project', 'services/gateway', 'uvicorn', 'marvi_gateway.app:app', '--host', '127.0.0.1', '--port', '8765') `
    -WorkingDirectory $repo -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDir 'gateway-test.log') `
    -RedirectStandardError (Join-Path $logDir 'gateway-test.err.log') -PassThru
$agent = Start-Process -FilePath $uv `
    -ArgumentList @('run', '--project', 'services/agent', 'python', '-m', 'marvi_agent.session', 'dev') `
    -WorkingDirectory $repo -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logDir 'agent-test.log') `
    -RedirectStandardError (Join-Path $logDir 'agent-test.err.log') -PassThru

try {
    Start-Sleep -Seconds 5
    $health = Invoke-RestMethod http://127.0.0.1:8765/health
    $session = Invoke-RestMethod -Method Post http://127.0.0.1:8765/livekit/session
    $env:MARVI_TEST_TOKEN = $session.token
    [pscustomobject]@{
        Gateway = $health.components.gateway.state
        LiveKit = $health.components.livekit.state
        Room = $session.room
        TokenBytes = $session.token.Length
    } | Format-List
    uv run --project services/agent python scripts/check_livekit_room.py
}
finally {
    Stop-Process -Id $agent.Id, $gateway.Id, $livekit.Id -Force -ErrorAction SilentlyContinue
}

Get-Content (Join-Path $logDir 'agent-test.log') -Tail 60
Get-Content (Join-Path $logDir 'agent-test.err.log') -Tail 80

