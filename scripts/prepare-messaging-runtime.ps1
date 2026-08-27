$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$serviceRoot = (Resolve-Path (Join-Path $repoRoot 'services\messaging')).Path
$packageRoot = Join-Path $serviceRoot 'marvi_messaging'
$engineRoot = Join-Path $packageRoot 'engine'
$stageRoot = Join-Path $repoRoot 'apps\desktop\resources\messaging-runtime'
$expectedStage = Join-Path $repoRoot 'apps\desktop\resources\messaging-runtime'

if ($stageRoot -ne $expectedStage) { throw "Unexpected messaging stage path: $stageRoot" }
if (-not (Test-Path (Join-Path $engineRoot 'gateway\run.py'))) {
  throw 'Bundled Marvi messaging engine is incomplete'
}
if (Test-Path -LiteralPath $stageRoot) {
  Remove-Item -LiteralPath $stageRoot -Recurse -Force
}

$runtimeStage = Join-Path $stageRoot 'runtime\marvi_messaging'
$pythonStage = Join-Path $stageRoot 'python'
New-Item -ItemType Directory -Path $runtimeStage, $pythonStage -Force | Out-Null

# Package the Marvi-owned runtime tree directly. Repository metadata, test
# fixtures, virtual environments, and bytecode are outside this boundary.
$runtimeFiles = @(
  Get-ChildItem -LiteralPath $packageRoot -File -Recurse | Where-Object {
    $_.FullName -notmatch '[\\/]__pycache__[\\/]' -and
    $_.FullName -notmatch '[\\/]\.venv[\\/]' -and
    $_.Extension -ne '.pyc'
  }
)
foreach ($runtimeFile in $runtimeFiles) {
  $relative = $runtimeFile.FullName.Substring($packageRoot.Length + 1)
  $destination = Join-Path $runtimeStage $relative
  $parent = Split-Path -Parent $destination
  if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
  Copy-Item -LiteralPath $runtimeFile.FullName -Destination $destination -Force
}

$pythonVersion = (Get-Content (Join-Path $engineRoot '.python-version') | Select-Object -First 1).Trim()
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
$exportArgs = @('export', '--project', $engineRoot, '--locked', '--no-dev', '--no-emit-project', '--output-file', $requirements)
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

$savedPythonPath = $env:PYTHONPATH
$savedUvOffline = $env:UV_OFFLINE
$savedPipIndex = $env:PIP_NO_INDEX
$savedNoBytecode = $env:PYTHONDONTWRITEBYTECODE
$savedMessagingHome = $env:MARVI_MESSAGING_HOME
$savedEngineRoot = $env:MARVI_MESSAGING_ENGINE_ROOT
$smokeProfile = Join-Path $stageRoot 'smoke-profile'
$smokeError = Join-Path $stageRoot 'smoke-stderr.txt'
try {
  $env:PYTHONPATH = Split-Path -Parent $runtimeStage
  $env:MARVI_MESSAGING_HOME = $smokeProfile
  $env:MARVI_MESSAGING_ENGINE_ROOT = Join-Path $runtimeStage 'engine'
  New-Item -ItemType Directory -Path $smokeProfile -Force | Out-Null
  '{}' | Set-Content -Encoding ascii (Join-Path $smokeProfile 'config.yaml')
  $env:UV_OFFLINE = '1'
  $env:PIP_NO_INDEX = '1'
  $env:PYTHONDONTWRITEBYTECODE = '1'
  $priorErrorAction = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  & $runtimePython -c "from marvi_messaging._engine import activate; activate(managed=True); import gateway.run" 2> $smokeError
  $smokeExitCode = $LASTEXITCODE
  $ErrorActionPreference = $priorErrorAction
  if ($smokeExitCode -ne 0) {
    Get-Content -LiteralPath $smokeError | Write-Host
    throw 'Bundled messaging runtime failed its offline import check'
  }
  & $runtimePython -m marvi_messaging.main gateway run --help | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Marvi messaging entrypoint failed its offline command check' }
} finally {
  $env:PYTHONPATH = $savedPythonPath
  $env:UV_OFFLINE = $savedUvOffline
  $env:PIP_NO_INDEX = $savedPipIndex
  $env:PYTHONDONTWRITEBYTECODE = $savedNoBytecode
  $env:MARVI_MESSAGING_HOME = $savedMessagingHome
  $env:MARVI_MESSAGING_ENGINE_ROOT = $savedEngineRoot
  if (Test-Path -LiteralPath $smokeProfile) { Remove-Item -LiteralPath $smokeProfile -Recurse -Force }
  if (Test-Path -LiteralPath $smokeError) { Remove-Item -LiteralPath $smokeError -Force }
}

$stagedFiles = (Get-ChildItem -LiteralPath $runtimeStage -File -Recurse | Measure-Object).Count
if ($stagedFiles -ne $runtimeFiles.Count) {
  throw "Messaging payload mismatch: source=$($runtimeFiles.Count), staged=$stagedFiles"
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
  schema = 2
  component = 'Marvi OS bundled messaging runtime'
  implementationCommit = '61977bb4d6b97ab2aece57d2405fa2f0b19e3ae0'
  runtimeFiles = $runtimeFiles.Count
  python = (& $runtimePython -c 'import platform; print(platform.python_version())').Trim()
  requirementsSha256 = $requirementsHash
  dependenciesInstalledAtBuild = $true
  runtimeDownloadsAllowed = $false
}
$manifest | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $stageRoot 'manifest.json')
Write-Host "Prepared self-contained messaging runtime: $stageRoot"
