import { execFile, spawn } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { delimiter, join, resolve } from 'node:path'
import { promisify } from 'node:util'

import type {
  MessagingPairingRequest,
  MessagingPreferences,
  MessagingStatus
} from '../shared/runtime'
import { stateDir } from './config'

const execFileAsync = promisify(execFile)

export const MESSAGING_SOURCE_COMMIT = '61977bb4d6b97ab2aece57d2405fa2f0b19e3ae0'

function preferencesPath(): string {
  return join(stateDir(), 'messaging.json')
}

export function messagingSourceRoot(repoRoot: string | null, resourcesRoot?: string): string {
  const packaged = resourcesRoot
    ? join(resourcesRoot, 'messaging', 'runtime', 'marvi_messaging', 'engine')
    : ''
  if (packaged && existsSync(join(packaged, 'gateway', 'run.py'))) return packaged
  return repoRoot
    ? join(repoRoot, 'services', 'messaging', 'marvi_messaging', 'engine')
    : ''
}

/** The messaging process never runs through uv. Installation/build creates
 * this interpreter and all locked dependencies before the desktop can start. */
export function messagingPython(sourceRoot: string): string {
  const runtimeRoot = resolve(sourceRoot, '..', '..')
  const packaged = resolve(runtimeRoot, '..', 'python', 'python.exe')
  const checkout = join(runtimeRoot, '.venv', 'Scripts', 'python.exe')
  return [packaged, checkout].find((candidate) => existsSync(candidate)) ?? ''
}

export function messagingLaunch(sourceRoot: string): {
  command: string
  args: string[]
  cwd: string
  env: Record<string, string>
} | null {
  const command = messagingPython(sourceRoot)
  const runtimeRoot = resolve(sourceRoot, '..', '..')
  return command && runtimeRoot
    ? {
        command,
        args: ['-m', 'marvi_messaging.main'],
        cwd: runtimeRoot,
        env: {
          PYTHONPATH: [runtimeRoot, sourceRoot].join(delimiter),
          MARVI_MESSAGING_ENGINE_ROOT: sourceRoot
        }
      }
    : null
}

export function defaultMessagingHome(): string {
  const configured = process.env['MARVI_MESSAGING_HOME']?.trim()
  return configured || join(stateDir(), 'messaging-agent')
}

export function readMessagingPreferences(): MessagingPreferences {
  const fallback = { enabled: false, home: defaultMessagingHome() }
  try {
    const parsed = JSON.parse(
      readFileSync(preferencesPath(), 'utf8')
    ) as Partial<MessagingPreferences>
    return {
      enabled: parsed.enabled === true,
      home: parsed.home?.trim() ? resolve(parsed.home) : fallback.home
    }
  } catch {
    return fallback
  }
}

export function writeMessagingPreferences(update: MessagingPreferences): MessagingPreferences {
  const next = {
    enabled: update.enabled === true,
    home: resolve(update.home?.trim() || defaultMessagingHome())
  }
  mkdirSync(stateDir(), { recursive: true })
  writeFileSync(preferencesPath(), `${JSON.stringify(next, null, 2)}\n`, { mode: 0o600 })
  return next
}

/** Read the platform enum from the bundled engine instead of maintaining a list
 * that inevitably drifts from the messaging engine. */
export function messagingPlatforms(sourceRoot: string): string[] {
  try {
    const source = readFileSync(join(sourceRoot, 'gateway', 'config.py'), 'utf8')
    const block = /class Platform\(Enum\):([\s\S]*?)(?=\nclass\s|$)/.exec(source)?.[1] ?? ''
    const values = [...block.matchAll(/^\s+[A-Z][A-Z0-9_]*\s*=\s*["']([^"']+)["']/gm)].map(
      (match) => match[1]
    )
    return [...new Set(values)].sort()
  } catch {
    return []
  }
}

export function messagingStatus(repoRoot: string | null, resourcesRoot?: string): MessagingStatus {
  const preferences = readMessagingPreferences()
  const sourceRoot = messagingSourceRoot(repoRoot, resourcesRoot)
  const launch = sourceRoot ? messagingLaunch(sourceRoot) : null
  const installed = Boolean(
    sourceRoot &&
    launch &&
    existsSync(join(sourceRoot, 'pyproject.toml')) &&
    existsSync(join(sourceRoot, 'gateway', 'run.py'))
  )
  return {
    ...preferences,
    installed,
    sourceRoot,
    sourceCommit: MESSAGING_SOURCE_COMMIT,
    platforms: installed ? messagingPlatforms(sourceRoot) : [],
    configured: existsSync(join(preferences.home, 'config.yaml')),
    setupCommand: launch
      ? `"${launch.command}" -m marvi_messaging.main setup gateway`
      : 'Bundled messaging runtime is not installed'
  }
}

export function shouldStartMessaging(status: MessagingStatus): boolean {
  return status.installed && status.configured && status.enabled
}

export function messagingEnvironment(home: string, parentPid: number): Record<string, string> {
  return {
    MARVI_MESSAGING_HOME: home,
    MARVI_MESSAGING_PARENT_PID: String(parentPid),
    // The bundled gateway has its own restart machinery. Electron is the
    // owner here, so it must exit back to our supervisor instead.
    MARVI_MESSAGING_EXTERNAL_SUPERVISOR: '1',
    MARVI_MESSAGING_IMPLEMENTATION_COMMIT: MESSAGING_SOURCE_COMMIT,
    UV_OFFLINE: '1',
    UV_PYTHON_DOWNLOADS: 'never',
    PIP_NO_INDEX: '1',
    PYTHONDONTWRITEBYTECODE: '1',
    PYTHONNOUSERSITE: '1',
    MARVI_MESSAGING_MANAGED: '1'
  }
}

/** Open Marvi's interactive adapter setup. Credentials are entered in that
 * process and written to its private home; they never cross renderer IPC. */
export function launchMessagingSetup(
  repoRoot: string | null,
  resourcesRoot: string | undefined,
  parentPid: number
): boolean {
  const status = messagingStatus(repoRoot, resourcesRoot)
  const launch = messagingLaunch(status.sourceRoot)
  if (!status.installed || !launch) return false
  mkdirSync(status.home, { recursive: true })
  try {
    const environment = messagingEnvironment(status.home, parentPid)
    // Setup writes the user's profile, so omit the runtime write lock.
    // Offline flags remain: setup cannot install or update code.
    delete environment['MARVI_MESSAGING_MANAGED']
    const child = spawn(launch.command, [...launch.args, 'setup', 'gateway'], {
      cwd: launch.cwd,
      detached: true,
      stdio: 'inherit',
      windowsHide: false,
      env: { ...process.env, ...environment, ...launch.env }
    })
    child.unref()
    return true
  } catch {
    return false
  }
}

function messagingAdminEnvironment(
  launch: NonNullable<ReturnType<typeof messagingLaunch>>,
  home: string,
  parentPid: number
): NodeJS.ProcessEnv {
  const environment = messagingEnvironment(home, parentPid)
  // Administrative commands write the private pairing/config store and do
  // not own the long-running gateway lifecycle.
  delete environment['MARVI_MESSAGING_MANAGED']
  return { ...process.env, ...environment, ...launch.env }
}

function pairingRows(value: unknown): MessagingPairingRequest[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (!item || typeof item !== 'object') return []
    const row = item as Record<string, unknown>
    if (
      typeof row.platform !== 'string' ||
      typeof row.request_id !== 'string' ||
      typeof row.user_id !== 'string' ||
      typeof row.user_name !== 'string' ||
      typeof row.age_minutes !== 'number'
    ) {
      return []
    }
    return [
      {
        platform: row.platform,
        requestId: row.request_id,
        userId: row.user_id,
        userName: row.user_name,
        ageMinutes: row.age_minutes
      }
    ]
  })
}

/** Run a bounded, non-shell Marvi administrative command. No package manager,
 * network installer, or upstream CLI participates in this path. */
async function runMessagingAdmin(
  repoRoot: string | null,
  resourcesRoot: string | undefined,
  parentPid: number,
  args: string[]
): Promise<string | null> {
  const status = messagingStatus(repoRoot, resourcesRoot)
  const launch = messagingLaunch(status.sourceRoot)
  if (!status.installed || !launch) return null
  mkdirSync(status.home, { recursive: true })
  try {
    const { stdout } = await execFileAsync(launch.command, [...launch.args, ...args], {
      cwd: launch.cwd,
      env: messagingAdminEnvironment(launch, status.home, parentPid),
      encoding: 'utf8',
      maxBuffer: 256 * 1024,
      timeout: 10_000,
      windowsHide: true
    })
    return stdout.trim()
  } catch {
    return null
  }
}

export async function listMessagingPairings(
  repoRoot: string | null,
  resourcesRoot: string | undefined,
  parentPid: number
): Promise<MessagingPairingRequest[]> {
  const output = await runMessagingAdmin(repoRoot, resourcesRoot, parentPid, ['pairing', 'list'])
  if (!output) return []
  try {
    return pairingRows(JSON.parse(output))
  } catch {
    return []
  }
}

export async function approveMessagingPairing(
  repoRoot: string | null,
  resourcesRoot: string | undefined,
  parentPid: number,
  platform: string,
  requestId: string
): Promise<boolean> {
  const status = messagingStatus(repoRoot, resourcesRoot)
  const normalizedPlatform = platform.trim().toLowerCase()
  const normalizedRequest = requestId.trim().toLowerCase()
  if (!status.platforms.includes(normalizedPlatform) || !/^[0-9a-f]{16}$/.test(normalizedRequest)) {
    return false
  }
  return (
    (await runMessagingAdmin(repoRoot, resourcesRoot, parentPid, [
      'pairing',
      'approve',
      normalizedPlatform,
      normalizedRequest
    ])) !== null
  )
}
