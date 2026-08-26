$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$vendorRoot = (Resolve-Path (Join-Path $repoRoot 'vendor\marvi-agent')).Path
$stageRoot = Join-Path $repoRoot 'apps\desktop\resources\messaging-runtime'
$expectedStage = Join-Path $repoRoot 'apps\desktop\resources\messaging-runtime'

if ($stageRoot -ne $expectedStage) {
  throw "Unexpected messaging stage path: $stageRoot"
}
if (-not (Test-Path (Join-Path $vendorRoot 'gateway\run.py'))) {
  throw 'Vendored messaging source is incomplete'
}
if (Test-Path -LiteralPath $stageRoot) {
  Remove-Item -LiteralPath $stageRoot -Recurse -Force
}

$sourceStage = Join-Path $stageRoot 'vendor'
$runtimeStage = Join-Path $stageRoot 'runtime\marvi_messaging'
$pythonStage = Join-Path $stageRoot 'python'
New-Item -ItemType Directory -Path $sourceStage, $runtimeStage, $pythonStage -Force | Out-Null

# Ship exactly the files Marvi tracks for the vendored tree. This excludes a
# developer .venv, caches, logs, and repository metadata by construction.
$vendorFiles = @(git -C $repoRoot -c core.quotepath=false ls-files -- vendor/marvi-agent)
foreach ($tracked in $vendorFiles) {
  $relative = $tracked.Substring('vendor/marvi-agent/'.Length)
  $destination = Join-Path $sourceStage $relative
  $parent = Split-Path -Parent $destination
  if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
  Copy-Item -LiteralPath (Join-Path $repoRoot $tracked) -Destination $destination -Force
}

$marviRuntimeRoot = Join-Path $repoRoot 'services\messaging\marvi_messaging'
$marviRuntimeFiles = @(Get-ChildItem -LiteralPath $marviRuntimeRoot -File -Recurse -Filter *.py)
foreach ($runtimeFile in $marviRuntimeFiles) {
  $relative = $runtimeFile.FullName.Substring($marviRuntimeRoot.Length + 1)
  $destination = Join-Path $runtimeStage $relative
  $parent = Split-Path -Parent $destination
  if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
  Copy-Item -LiteralPath $runtimeFile.FullName -Destination $destination -Force
}

$pythonVersion = (Get-Content (Join-Path $vendorRoot '.python-version') | Select-Object -First 1).Trim()
& uv python install $pythonVersion
if ($LASTEXITCODE -ne 0) { throw 'Could not provision the bundled messaging Python runtime' }
$managedPython = (& uv python find --managed-python $pythonVersion | Select-Object -Last 1).Trim()
if (-not (Test-Path -LiteralPath $managedPython)) { throw "Managed Python not found: $managedPython" }
$managedRoot = Split-Path -Parent $managedPython

& robocopy $managedRoot $pythonStage /MIR /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -gt 7) { throw "Could not stage messaging Python (robocopy $LASTEXITCODE)" }
$runtimePython = Join-Path $pythonStage 'python.exe'
if (-not (Test-Path -LiteralPath $runtimePython)) { throw 'Bundled Python executable is missing' }

$requirements = Join-Path $stageRoot 'requirements.lock'
$overrides = Join-Path $stageRoot 'overrides.txt'
$extras = @('all', 'messaging', 'slack', 'matrix', 'wecom', 'dingtalk', 'feishu', 'homeassistant', 'sms', 'teams')
$exportArgs = @('export', '--project', $vendorRoot, '--locked', '--no-dev', '--no-emit-project', '--output-file', $requirements)
foreach ($extra in $extras) { $exportArgs += @('--extra', $extra) }
& uv @exportArgs | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not export locked messaging dependencies' }

@(
  'pynacl>=1.6,<1.7'
  'cryptography>=50,<51'
  "python-olm ; sys_platform == 'no-such-platform'"
) | Set-Content -Encoding ascii $overrides

& uv pip install --python $runtimePython --system --break-system-packages --requirements $requirements --overrides $overrides --strict
if ($LASTEXITCODE -ne 0) { throw 'Could not install locked messaging dependencies into the bundle' }

$previousPythonPath = $env:PYTHONPATH
$previousUvOffline = $env:UV_OFFLINE
$previousPipIndex = $env:PIP_NO_INDEX
$previousNoBytecode = $env:PYTHONDONTWRITEBYTECODE
$previousMessagingHome = $env:MARVI_MESSAGING_HOME
$previousVendorRoot = $env:MARVI_MESSAGING_VENDOR_ROOT
$smokeHome = Join-Path $stageRoot 'smoke-home'
$smokeError = Join-Path $stageRoot 'smoke-stderr.txt'
try {
  $env:PYTHONPATH = (Split-Path -Parent $runtimeStage)
  $env:MARVI_MESSAGING_HOME = $smokeHome
  New-Item -ItemType Directory -Path $env:MARVI_MESSAGING_HOME -Force | Out-Null
  '{}' | Set-Content -Encoding ascii (Join-Path $env:MARVI_MESSAGING_HOME 'config.yaml')
  $env:MARVI_MESSAGING_VENDOR_ROOT = $sourceStage
  $env:UV_OFFLINE = '1'
  $env:PIP_NO_INDEX = '1'
  $env:PYTHONDONTWRITEBYTECODE = '1'
  $previousErrorAction = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  & $runtimePython -c "from marvi_messaging._vendor import activate; activate(managed=True); import gateway.run" 2> $smokeError
  $smokeExitCode = $LASTEXITCODE
  $ErrorActionPreference = $previousErrorAction
  if ($smokeExitCode -ne 0) {
    Get-Content -LiteralPath $smokeError | Write-Host
    throw 'Bundled messaging runtime failed its offline import check'
  }
  Write-Host 'marvi-messaging-runtime-ok'
  & $runtimePython -m marvi_messaging.main gateway run --help | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Marvi messaging entrypoint failed its offline command check' }
} finally {
  $env:PYTHONPATH = $previousPythonPath
  $env:UV_OFFLINE = $previousUvOffline
  $env:PIP_NO_INDEX = $previousPipIndex
  $env:PYTHONDONTWRITEBYTECODE = $previousNoBytecode
  $env:MARVI_MESSAGING_HOME = $previousMessagingHome
  $env:MARVI_MESSAGING_VENDOR_ROOT = $previousVendorRoot
  if (Test-Path -LiteralPath $smokeHome) {
    Remove-Item -LiteralPath $smokeHome -Recurse -Force
  }
  if (Test-Path -LiteralPath $smokeError) {
    Remove-Item -LiteralPath $smokeError -Force
  }
}

# Python writes bytecode beside imported source by default. The smoke test must
# not change the exact vendored payload that will be shipped.
Get-ChildItem -LiteralPath $sourceStage -Directory -Recurse -Filter __pycache__ |
  Remove-Item -Recurse -Force
$stagedSourceFiles = (Get-ChildItem -LiteralPath $sourceStage -File -Recurse | Measure-Object).Count
if ($stagedSourceFiles -ne $vendorFiles.Count) {
  throw "Messaging source payload mismatch: tracked=$($vendorFiles.Count), staged=$stagedSourceFiles"
}

$requirementsStream = [System.IO.File]::OpenRead($requirements)
try {
  $sha256 = [System.Security.Cryptography.SHA256]::Create()
  $requirementsHash = [System.BitConverter]::ToString($sha256.ComputeHash($requirementsStream)).Replace('-', '').ToLowerInvariant()
} finally {
  if ($sha256) { $sha256.Dispose() }
  $requirementsStream.Dispose()
}

$manifest = [ordered]@{
  schema = 1
  source = 'https://github.com/xRetr00/Marvi.git'
  sourceCommit = '61977bb4d6b97ab2aece57d2405fa2f0b19e3ae0'
  upstreamFiles = $vendorFiles.Count
  marviRuntimeFiles = $marviRuntimeFiles.Count
  python = (& $runtimePython -c 'import platform; print(platform.python_version())').Trim()
  requirementsSha256 = $requirementsHash
}
$manifest | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $stageRoot 'manifest.json')
Write-Host "Prepared standalone messaging runtime: $stageRoot"
