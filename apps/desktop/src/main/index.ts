import { execFile, spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { promisify } from 'node:util'

import {
  app,
  BrowserWindow,
  clipboard,
  dialog,
  ipcMain,
  Menu,
  nativeImage,
  screen,
  session,
  shell,
  Tray
} from 'electron'
import { is } from '@electron-toolkit/utils'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'fs'
import { readFile } from 'fs/promises'
import { join, resolve } from 'path'
import icon from '../../resources/icon.png?asset'
import trayIcon from '../../resources/tray-icon.png?asset'
import {
  gatewayBind,
  gatewayUrl,
  livekitBind,
  livekitCredentials,
  livekitServerPath,
  logsDir,
  stateDir
} from './config'
import { configure as configureLogging, desktop, installCatchers } from './logger'
import { killStrays, reclaimPort } from './processes'
import {
  offlineRuntime,
  offlineRuntimeFrom,
  normalizeRuntimeStatus,
  reconcileRuntimeStatus
} from './gateway-runtime'
import { type ServiceReport, ServiceSupervisor, findUv } from './services'
import {
  islandWindowBounds,
  normalizeIslandContentSize,
  normalizeIslandInteractionMode,
  type IslandContentSize,
  type IslandPlacement
} from './island-window'
import {
  DEFAULT_PET_PREFERENCES,
  normalizePetPreferences,
  petLookDirection,
  petSpriteBounds,
  petWindowBounds,
  pointInBounds,
  type PetPreferences,
  type RectangleLike
} from './pet-window'
import { NativePetHost, petActionPage, petTaskCount, resolvePetHostPaths } from './pet-host'
import { maintenancePowerShellArgs } from './maintenance-terminal'
import { restartApplication, shutdownApplication } from './lifecycle-actions'
import {
  canUpdate,
  checkForUpdate,
  consumeUpdateResult,
  getUpdateChannel,
  resolveBootstrap,
  setUpdateChannel,
  startUpdate,
  updateInProgress,
  updateStateDir
} from './updater'
import { isComposioConnectUrl, normaliseAccountPage } from './account-runtime'
import {
  isSafeConnectUrl,
  normaliseConnectorRow,
  normaliseConnectorsPage
} from './connector-runtime'
import type {
  AccountToolkit,
  AssistantState,
  ConnectorRow,
  ConnectorsPage,
  McpRegistryPage,
  McpServersPage,
  ModelPage,
  ProviderPage,
  ProviderRow,
  UsagePage,
  RuntimeStatus,
  UpstreamPage,
  RecogniserPage,
  VoiceClonePage,
  VoicePage,
  LanguagePolicy,
  MemoryPolicy,
  VoiceVerdict,
  SkillProposal,
  WakeStatus,
  WorkspacePolicy
} from '../shared/runtime'

let mainWindow: BrowserWindow | null = null
let islandWindow: BrowserWindow | null = null
let petHost: NativePetHost | null = null
let petBounds: RectangleLike | null = null
let petRestartTimer: NodeJS.Timeout | null = null
let tray: Tray | null = null
let gatewayPoll: NodeJS.Timeout | null = null
let petCursorPoll: NodeJS.Timeout | null = null
let supervisor: ServiceSupervisor | null = null
let serviceReports: ServiceReport[] = []
let repoRoot: string | null = null
let runtimeStatus: RuntimeStatus = offlineRuntime('unknown')
let islandPlacement: IslandPlacement = { displayId: null, alignment: 'center' }
let islandContentSize: IslandContentSize = { width: 76, height: 8 }
let petPreferences: PetPreferences = { ...DEFAULT_PET_PREFERENCES }
let isQuitting = false
let translucencyIntensity = 0

// The renderer owns the translucency lever (0–100) and mirrors it here; the
// main process maps it to native window opacity. Floor the most see-through
// setting at 0.3 so it stays usable. 0 = fully opaque.
/** The Gateway speaks snake_case; the renderer types are camelCase. */
/** Marvi's own renderer, whether packaged (file://) or the dev server. */
function isMarviPage(url: string): boolean {
  if (!url) return false
  return (
    url.startsWith('file://') ||
    url.startsWith('http://localhost:') ||
    url.startsWith('http://127.0.0.1:')
  )
}

/** Server-Sent Events separate frames with a blank line. */
const SSE_FRAME_SEPARATOR = String.fromCharCode(10, 10)

function voiceVerdict(raw: unknown): VoiceVerdict | undefined {
  if (!isRecord(raw)) return undefined
  return {
    model: String(raw.model ?? ''),
    reasons: raw.reasons === true,
    reasoningLockedOn: raw.reasoning_locked_on === true,
    effort: String(raw.effort ?? ''),
    warning: String(raw.warning ?? '')
  }
}

function normaliseModelPage(body: unknown): ModelPage | null {
  const page = body as { providers?: Array<Record<string, never>> }
  if (!page || !Array.isArray(page.providers)) return null
  const number = (value: unknown): number | null =>
    // Null and zero mean different things here: a model can genuinely be free,
    // and a price the provider did not publish must not read as free.
    value === null || value === undefined ? null : Number(value)
  return {
    providers: page.providers.map((raw) => {
      const row = raw as Record<string, never>
      const models = Array.isArray(row.models) ? (row.models as Array<Record<string, never>>) : []
      return {
        provider: String(row.provider ?? ''),
        label: String(row.label ?? ''),
        selected: String(row.selected ?? ''),
        routesUpstream: Boolean(row.routes_upstream),
        reachable: Boolean(row.reachable),
        voice: voiceVerdict(row.voice as unknown),
        models: models.map((entry) => ({
          id: String(entry.id ?? ''),
          name: String(entry.name ?? entry.id ?? ''),
          provider: String(entry.provider ?? row.provider ?? ''),
          context: Number(entry.context ?? 0),
          efforts: Array.isArray(entry.efforts) ? (entry.efforts as string[]).map(String) : [],
          reasons: Boolean(entry.reasons),
          promptPerMillion: number(entry.prompt_per_million),
          completionPerMillion: number(entry.completion_per_million),
          vision: Boolean(entry.vision)
        }))
      }
    })
  }
}

function normaliseUpstreamPage(body: unknown): UpstreamPage | null {
  const page = body as {
    model?: string
    route?: Record<string, Record<string, unknown>>
    policies?: string[]
    upstreams?: Array<Record<string, never>>
  }
  if (!page || !Array.isArray(page.upstreams)) return null
  const number = (value: unknown): number | null =>
    value === null || value === undefined ? null : Number(value)
  return {
    model: String(page.model ?? ''),
    route: page.route ?? {},
    policies: Array.isArray(page.policies) ? page.policies.map(String) : [],
    upstreams: page.upstreams.map((raw) => {
      const row = raw as Record<string, never>
      return {
        slug: String(row.slug ?? ''),
        name: String(row.name ?? row.slug ?? ''),
        context: Number(row.context ?? 0),
        quantization: String(row.quantization ?? ''),
        promptPerMillion: number(row.prompt_per_million),
        completionPerMillion: number(row.completion_per_million),
        latencyMs: number(row.latency_ms),
        throughput: number(row.throughput),
        uptime: number(row.uptime)
      }
    })
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

/** The file policy, in the renderer's spelling. */
function normaliseWorkspace(body: unknown): WorkspacePolicy | null {
  if (!isRecord(body)) return null
  const strings = (value: unknown): string[] =>
    Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
  const scope = (value: unknown): 'strict' | 'general' =>
    value === 'general' ? 'general' : 'strict'
  const tools = isRecord(body.tools) ? body.tools : {}
  return {
    root: typeof body.root === 'string' ? body.root : '',
    rootExists: body.root_exists === true,
    readScope: scope(body.read_scope),
    writeScope: scope(body.write_scope),
    secretAccess:
      body.secret_access === 'masked' || body.secret_access === 'full' ? body.secret_access : 'off',
    blacklist: strings(body.blacklist),
    builtin: (Array.isArray(body.builtin) ? body.builtin : []).filter(isRecord).map((rule) => ({
      pattern: String(rule.pattern ?? ''),
      why: String(rule.why ?? ''),
      reading: rule.reading === true,
      secret: rule.secret === true
    })),
    tools: { read: strings(tools.read), write: strings(tools.write) }
  }
}

/** The language policy, in the renderer's spelling. */
function normaliseLanguage(body: unknown): LanguagePolicy | null {
  if (!isRecord(body)) return null
  const options = (value: unknown): { code: string; name: string; locked: boolean }[] =>
    (Array.isArray(value) ? value : []).filter(isRecord).map((row) => ({
      code: String(row.code ?? ''),
      name: String(row.name ?? ''),
      locked: row.locked === true
    }))
  return {
    understand: typeof body.understand === 'string' ? body.understand : 'auto',
    understandOptions: options(body.understand_options),
    speak: typeof body.speak === 'string' ? body.speak : 'en',
    speakOptions: options(body.speak_options).map(({ code, name }) => ({ code, name })),
    enforceable: body.enforceable === true,
    englishModelInstalled: body.english_model_installed === true
  }
}

/** The memory policy, in the renderer's spelling. */
function normaliseProposal(body: Record<string, unknown>): SkillProposal | null {
  const name = typeof body.name === 'string' ? body.name : ''
  const skillBody = typeof body.body === 'string' ? body.body : ''
  // Both or neither. A proposal missing its body is a review sheet with
  // nothing to review, and the button under it still writes a file.
  if (!name || !skillBody) return null
  return {
    act: body.act === 'patch' ? 'patch' : 'create',
    name,
    description: typeof body.description === 'string' ? body.description : '',
    body: skillBody,
    why: typeof body.why === 'string' ? body.why : ''
  }
}

function normaliseMemory(body: unknown): MemoryPolicy | null {
  if (!isRecord(body)) return null
  const embedding = isRecord(body.embedding) ? body.embedding : {}
  const source =
    embedding.source === 'local' || embedding.source === 'provider' ? embedding.source : 'off'
  return {
    provider: body.provider === 'honcho' || body.provider === 'mem0' ? body.provider : 'local',
    providers: Array.isArray(body.providers)
      ? body.providers.filter((item): item is string => typeof item === 'string')
      : ['local', 'honcho', 'mem0'],
    providerUrl: typeof body.url === 'string' ? body.url : '',
    providerKeySet: body.key_set === true,
    userId: typeof body.user_id === 'string' ? body.user_id : 'marvi-user',
    workspace: typeof body.workspace === 'string' ? body.workspace : 'marvi-os',
    source,
    sources: Array.isArray(embedding.sources)
      ? embedding.sources.filter((item): item is string => typeof item === 'string')
      : ['off', 'local', 'provider'],
    model: typeof embedding.model === 'string' ? embedding.model : '',
    url: typeof embedding.url === 'string' ? embedding.url : '',
    keySet: embedding.key_set === true,
    defaultLocalModel:
      typeof embedding.default_local_model === 'string' ? embedding.default_local_model : '',
    defaultProviderModel:
      typeof embedding.default_provider_model === 'string' ? embedding.default_provider_model : '',
    role: typeof body.role === 'string' ? body.role : 'memory',
    roleConfigured: body.role_configured === true,
    // Defaulted true to match the Gateway: an older Gateway that does not
    // report this is one where the reader is on, and showing the toggle off
    // would invite somebody to "enable" what is already running.
    reader: body.reader !== false
  }
}

function normaliseProviderPage(body: unknown): ProviderPage | null {
  const page = body as {
    providers?: Array<Record<string, never>>
    selected?: string | null
    settings?: Record<string, string>
    totals?: Record<string, number>
  }
  if (!page || !Array.isArray(page.providers)) return null
  const usage = (row: Record<string, number> | undefined): ProviderRow['usage'] => ({
    input: Number(row?.input ?? 0),
    output: Number(row?.output ?? 0),
    cachedInput: Number(row?.cached_input ?? 0),
    billable: Number(row?.billable ?? 0)
  })
  return {
    providers: page.providers.map((raw) => {
      const row = raw as Record<string, never>
      return {
        name: String(row.name ?? ''),
        label: String(row.label ?? ''),
        accessPath: (row.access_path ?? 'api') as ProviderRow['accessPath'],
        apiMode: String(row.api_mode ?? ''),
        authType: String(row.auth_type ?? ''),
        configured: Boolean(row.configured),
        baseUrl: String(row.base_url ?? ''),
        models: {
          main: String((row.models as Record<string, string>)?.main ?? ''),
          aux: String((row.models as Record<string, string>)?.aux ?? ''),
          vision: String((row.models as Record<string, string>)?.vision ?? '')
        },
        env: {
          key: String((row.env as Record<string, string>)?.key ?? ''),
          model: String((row.env as Record<string, string>)?.model ?? ''),
          url: String((row.env as Record<string, string>)?.url ?? ''),
          effort: String((row.env as Record<string, string>)?.effort ?? '')
        },
        limits: {
          style: String((row.limits as Record<string, string>)?.style ?? 'none'),
          windows: ((row.limits as Record<string, string[][]>)?.windows ?? []) as string[][],
          readable: Boolean((row.limits as Record<string, boolean>)?.readable),
          note: String((row.limits as Record<string, string>)?.note ?? '')
        },
        usage: usage(row.usage as Record<string, number> | undefined),
        cooldown: (row.cooldown ?? null) as ProviderRow['cooldown'],
        oauth: (row.oauth ?? null) as ProviderRow['oauth'],
        warning: (row.warning ?? null) as string | null,
        reachable: (row.reachable ?? null) as boolean | null
      }
    }),
    selected: page.selected ?? null,
    settings: page.settings ?? {},
    totals: usage(page.totals)
  }
}

function normaliseUsagePage(body: unknown): UsagePage | null {
  const page = body as Record<string, unknown>
  if (!page || !Array.isArray(page.providers) || !Array.isArray(page.daily)) return null
  const counters = (raw: unknown): UsagePage['totals'] => {
    const row = (raw ?? {}) as Record<string, unknown>
    return {
      input: Number(row.input ?? 0),
      output: Number(row.output ?? 0),
      cachedInput: Number(row.cached_input ?? 0),
      reasoning: Number(row.reasoning ?? 0),
      billable: Number(row.billable ?? 0)
    }
  }
  const account = (raw: unknown): UsagePage['providers'][number]['account'] => {
    if (!raw || typeof raw !== 'object') return null
    const value = raw as Record<string, unknown>
    return {
      state: value.state === 'error' ? 'error' : 'ready',
      scope: value.scope ? String(value.scope) : undefined,
      currency: value.currency ? String(value.currency) : undefined,
      spent: value.spent == null ? null : Number(value.spent),
      periodSpent: value.period_spent == null ? null : Number(value.period_spent),
      remaining: value.remaining == null ? null : Number(value.remaining),
      limit: value.limit == null ? null : Number(value.limit),
      balances: Array.isArray(value.balances)
        ? value.balances.map((row) => ({
            currency: String((row as Record<string, unknown>).currency ?? ''),
            remaining: String((row as Record<string, unknown>).remaining ?? '')
          }))
        : undefined,
      detail: value.detail ? String(value.detail) : undefined
    }
  }
  return {
    totals: counters(page.totals),
    providers: page.providers.map((raw) => {
      const row = raw as Record<string, unknown>
      return {
        name: String(row.name ?? ''),
        label: String(row.label ?? ''),
        accessPath: (row.access_path ?? 'api') as 'api' | 'plan' | 'local',
        configured: Boolean(row.configured),
        usage: counters(row.usage),
        account: account(row.account),
        accountCollection: String(row.account_collection ?? '')
      }
    }),
    daily: page.daily.map((raw) => {
      const row = raw as Record<string, unknown>
      return { date: String(row.date ?? ''), ...counters(row) }
    }),
    hourly: Array.isArray(page.hourly)
      ? page.hourly.map((raw) => {
          const row = raw as Record<string, unknown>
          return { hour: String(row.hour ?? ''), ...counters(row) }
        })
      : [],
    account: {},
    updatedAt: page.updated_at ? String(page.updated_at) : null
  }
}

function gateway(): string {
  return gatewayUrl(repoRoot)
}

/**
 * One fetch helper for the read-mostly Gateway endpoints.
 *
 * Every one of these had the same six lines of try/catch/timeout around it, and
 * six copies of a timeout is five chances to pick the wrong one.
 */
/**
 * The per-launch secret every child gets, and this process's proof of being it.
 *
 * Module scope rather than rebuilt with `childEnv`, because the endpoints that
 * check it are also called from here -- and a restart that rolled the token
 * would leave this process unable to reach the Gateway it just started.
 * New every launch and never written to disk. See marvi_gateway/localauth.py.
 */
const localToken = randomBytes(32).toString('hex')

function localHeaders(): Record<string, string> {
  return { 'x-marvi-local': localToken }
}

async function gatewayJson(path: string, init?: RequestInit, timeoutMs = 10_000): Promise<unknown> {
  try {
    const response = await fetch(`${gateway()}${path}`, {
      ...init,
      signal: AbortSignal.timeout(timeoutMs)
    })
    return response.ok ? await response.json() : null
  } catch {
    return null
  }
}

async function gatewayFailure(response: Response, fallback: string): Promise<Error> {
  try {
    const body = (await response.json()) as { detail?: unknown; error?: unknown }
    const detail = body.detail ?? body.error
    if (typeof detail === 'string' && detail.trim()) return new Error(detail)
  } catch {
    // A non-JSON error still gets an honest HTTP fallback.
  }
  return new Error(`${fallback} (HTTP ${response.status})`)
}

function windowOpacity(): number {
  return 1 - (translucencyIntensity / 100) * 0.7
}

function applyWindowTranslucency(window: BrowserWindow | null): void {
  if (!window || window.isDestroyed() || typeof window.setOpacity !== 'function') return
  try {
    window.setOpacity(windowOpacity())
  } catch {
    // Opacity is cosmetic; never fail lifecycle over it.
  }
}

function windowStatePayload(): { isMaximized: boolean } {
  return { isMaximized: mainWindow?.isMaximized() ?? false }
}

function broadcastWindowState(): void {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('marvi:window-state', windowStatePayload())
  }
}

/**
 * Find the checkout that owns this install.
 *
 * Marvi OS ships as a git checkout (that is what makes the updater work), and
 * the Python services live in it rather than inside the asar. A packaged build
 * sits at apps/desktop/dist/win-unpacked, so walk up until `services/gateway`
 * appears instead of guessing a fixed depth.
 */
function findRepoRoot(): string | null {
  let dir = resolve(app.getAppPath())
  for (let hop = 0; hop < 8; hop++) {
    if (existsSync(join(dir, 'services', 'gateway', 'pyproject.toml'))) return dir
    const parent = resolve(dir, '..')
    if (parent === dir) break
    dir = parent
  }
  return null
}

function startVoiceStack(): void {
  // Logging before anything can fail, so a startup failure is recorded rather
  // than being the one thing nothing wrote down.
  configureLogging(logsDir())
  installCatchers()
  desktop.info('starting the voice stack')
  if (process.env['MARVI_MANAGE_VOICE_STACK'] === '0') {
    desktop.info('MARVI_MANAGE_VOICE_STACK=0, leaving the services alone')
    return
  }
  repoRoot = findRepoRoot()
  if (!repoRoot) {
    // Nothing to start and no way to start it: say so instead of leaving the
    // shell on a connecting animation that will never finish.
    desktop.error('no Marvi OS checkout found; the Python services cannot be started')
    publishRuntime({
      ...offlineRuntime(app.getVersion()),
      state: 'error',
      components: {
        gateway: {
          state: 'error',
          detail: 'No Marvi OS checkout found; run from a git install.'
        }
      }
    })
    return
  }

  // Anything left running from a session that did not shut down cleanly. An
  // orphaned Gateway holds port 8765, and the new one then fails to bind for a
  // reason that looks like nothing at all.
  const strays = killStrays(repoRoot ?? undefined)
  if (strays > 0) desktop.warn(`stopped ${strays} leftover process(es) from a previous session`)

  // And the port, which the sweep above cannot reach: it is scoped to this
  // install root, and a Gateway from a second installation holding 8765 is
  // deliberately left alone. Ownership is the question that matters there, not
  // which checkout it came from -- one whose parent is gone belongs to nobody.
  const reclaimed = reclaimPort(Number(gatewayBind(repoRoot).port))
  if (reclaimed) desktop.warn(reclaimed)

  const uv = findUv()
  if (!uv) {
    desktop.error('uv was not found on PATH or in any known install location')
    // The most common failure on a fresh machine, and previously invisible.
    // Name it rather than letting it surface as a generic spawn error.
    publishRuntime({
      ...offlineRuntime(app.getVersion()),
      state: 'error',
      components: {
        gateway: {
          state: 'error',
          detail: 'uv was not found. Install it from astral.sh/uv, then restart Marvi.'
        }
      }
    })
    return
  }

  const bind = gatewayBind(repoRoot)
  const livekit = livekitServerPath(repoRoot)
  const lk = livekitBind(repoRoot)

  // Handed to every child rather than left to a .env nobody ships. The agent
  // exits immediately without LIVEKIT_URL, and it is the shell that knows it.
  const credentials = livekitCredentials()
  const childEnv: Record<string, string> = {
    LIVEKIT_URL: process.env['LIVEKIT_URL'] ?? `ws://${lk.host}:${lk.port}`,
    LIVEKIT_API_KEY: credentials.key,
    LIVEKIT_API_SECRET: credentials.secret,
    MARVI_GATEWAY_URL: gateway(),
    // The one endpoint that answers with a raw provider API key is
    // /providers/voice, and it used to answer to anything that could reach
    // loopback -- including any page in any browser on this machine. Both
    // children are started from here with the same value, which is what
    // distinguishes the agent asking from a tab asking. New every launch, and
    // never written to disk. See marvi_gateway/localauth.py.
    MARVI_LOCAL_TOKEN: localToken,
    MARVI_HOME: stateDir(),
    MARVI_LOG_DIR: logsDir(),
    // So a child can notice this process going away and stop on its own.
    //
    // `before-quit` already stops everything on a clean exit, and a clean exit
    // was never the problem. What leaves a Gateway holding port 8765 overnight
    // is this process being killed — and then nothing runs the code that would
    // have stopped anything.
    MARVI_PARENT_PID: String(process.pid),
    // Python's stdout on Windows is the console codepage — cp1252 here — and
    // every log line with an em dash, an ellipsis or a name that is not Latin-1
    // raised UnicodeEncodeError inside `logging` itself. The line was lost and
    // a forty-line traceback was written in its place: six of them in one voice
    // session, each hiding whatever it was trying to say.
    //
    // Inherited by everything downstream, which matters because the LiveKit
    // worker spawns its own job processes and they are where the transcript is
    // written.
    PYTHONIOENCODING: 'utf-8'
  }

  supervisor = new ServiceSupervisor((reports) => {
    serviceReports = reports
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('marvi:services', reports)
    }
  })

  supervisor.add({
    name: 'livekit',
    // Swept before starting, so a restart never leaves two.
    match: /livekit-server/i,
    installRoot: repoRoot ?? undefined,
    command: livekit,
    // `--keys` rather than `--dev`'s published devkey/secret pair. See
    // livekitCredentials().
    args: ['--dev', '--bind', lk.host, '--keys', `${credentials.key}: ${credentials.secret}`],
    cwd: repoRoot,
    env: childEnv,
    // Optional: a cloud LiveKit URL needs no local server.
    when: () => existsSync(livekit)
  })
  supervisor.add({
    name: 'gateway',
    // Swept before starting, so a restart never leaves two.
    match: /marvi_gateway/i,
    installRoot: repoRoot ?? undefined,
    // Only for explaining a bind failure: the one exit whose cause is another
    // process entirely, and worth naming rather than retrying past.
    port: Number(bind.port),
    command: uv,
    args: [
      'run',
      '--project',
      'services/gateway',
      'uvicorn',
      'marvi_gateway.app:app',
      '--host',
      bind.host,
      '--port',
      bind.port
    ],
    cwd: repoRoot,
    env: childEnv
  })
  supervisor.add({
    name: 'agent',
    // Swept before starting, so a restart never leaves two.
    match: /marvi_agent\.session/i,
    installRoot: repoRoot ?? undefined,
    command: uv,
    // `start`, not `dev`. Dev mode is LiveKit's development runner -- it is
    // deprecated, it prints "in-process auto-reload has been removed", and it
    // does not warm job processes, so every job began with "no warmed process
    // available for job, waiting for one to be created" and then ran cold.
    // A shipped product has no business running the framework's dev server.
    args: ['run', '--project', 'services/agent', 'python', '-m', 'marvi_agent.session', 'start'],
    cwd: repoRoot,
    env: childEnv
  })
  supervisor.startAll()
}

const execFileAsync = promisify(execFile)

/**
 * Turn the login-time wake word listener on or off, and say what it is doing.
 *
 * Shelled out to the Agent's own module rather than written from here. The
 * registry work is one implementation in one place, and this side has the two
 * things that side cannot know: where `uv` is, and where this executable
 * actually lives -- which changes on every update.
 */
/** Where the wake listener lives: packaged beside the app, or built in place. */
function wakeHostPath(): string {
  const packaged = join(process.resourcesPath, 'wake-host', 'marvi-wake-host.exe')
  if (existsSync(packaged)) return packaged
  return resolve(
    __dirname,
    '..',
    '..',
    '..',
    'wake-host',
    'target',
    'release',
    'marvi-wake-host.exe'
  )
}

/**
 * Start, stop, or ask after the wake listener.
 *
 * It used to be `uv run python -m marvi_agent.wake_autostart` writing a Run key
 * that pointed at an interpreter inside a virtual environment several
 * directories away — which stopped resolving after a reinstall, and left a
 * feature that looked registered and could not run.
 *
 * The listener owns its own registration now. It knows where it is; nothing
 * here has to tell it, and an update that moves it re-registers on next launch.
 */
async function wakeAutostart(
  action: 'enable' | 'disable' | 'status',
  device = ''
): Promise<{ autostart: boolean; running: boolean }> {
  const fallback = { autostart: false, running: false }
  const listener = wakeHostPath()
  if (!existsSync(listener)) return fallback

  try {
    if (action === 'status') {
      const { stdout } = await execFileAsync(listener, ['--autostart', 'status'], {
        windowsHide: true
      })
      const on = stdout.trim() === 'on'
      return { autostart: on, running: on }
    }
    const on = action === 'enable'
    await execFileAsync(listener, ['--autostart', on ? 'on' : 'off'], { windowsHide: true })
    if (on) {
      // Started now as well as at next login, so enabling it in Settings does
      // something you can hear rather than something you have to reboot for.
      // The chosen microphone rides in the environment: the listener re-reads
      // it on start, so changing it is a restart rather than a re-registration.
      const child = spawn(listener, [], {
        detached: true,
        stdio: 'ignore',
        windowsHide: true,
        env: {
          ...process.env,
          MARVI_APP_COMMAND: app.getPath('exe'),
          ...(device.trim() ? { MARVI_WAKE_DEVICE: device.trim() } : {})
        }
      })
      child.unref()
    }
    return { autostart: on, running: on }
  } catch {
    return fallback
  }
}

type RendererSurface = 'main' | 'island'

function rendererUrl(surface: RendererSurface): string {
  return `${process.env['ELECTRON_RENDERER_URL']}?surface=${surface}`
}

function loadSurface(window: BrowserWindow, surface: RendererSurface): void {
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    void window.loadURL(rendererUrl(surface))
    return
  }

  void window.loadFile(join(__dirname, '../renderer/index.html'), {
    query: { surface }
  })
}

function createMainWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1180,
    height: 760,
    minWidth: 920,
    minHeight: 620,
    show: false,
    autoHideMenuBar: true,
    // Hidden titlebar: the renderer owns the 34px surface and
    // Electron paints the native Windows controls into its right edge.
    titleBarStyle: 'hidden',
    titleBarOverlay: {
      color: 'rgba(1, 0, 0, 0)',
      height: 34,
      symbolColor: '#b8bcc4'
    },
    backgroundColor: '#050607',
    opacity: windowOpacity(),
    title: 'Marvi OS',
    icon,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      sandbox: true
    }
  })

  window.once('ready-to-show', () => window.show())
  window.on('maximize', broadcastWindowState)
  window.on('unmaximize', broadcastWindowState)
  window.on('close', (event) => {
    if (isQuitting) return
    event.preventDefault()
    window.hide()
  })
  window.on('closed', () => {
    mainWindow = null
  })
  window.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url)
    return { action: 'deny' }
  })
  loadSurface(window, 'main')
  return window
}

function sizeAndPositionIsland(window: BrowserWindow, contentSize: IslandContentSize): void {
  islandContentSize = contentSize
  const selectedDisplay = screen
    .getAllDisplays()
    .find((display) => display.id === islandPlacement.displayId)
  const currentDisplay = selectedDisplay ?? screen.getDisplayMatching(window.getBounds())
  const display = currentDisplay.bounds.width
    ? currentDisplay
    : screen.getDisplayNearestPoint(screen.getCursorScreenPoint())
  window.setBounds(
    islandWindowBounds(display.workArea, contentSize, islandPlacement.alignment),
    false
  )
}

function createIslandWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 100,
    height: 32,
    show: false,
    frame: false,
    transparent: true,
    resizable: false,
    movable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    focusable: false,
    hasShadow: false,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      sandbox: true
    }
  })

  window.setAlwaysOnTop(true, 'screen-saver')
  window.setIgnoreMouseEvents(true, { forward: true })
  window.setVisibleOnAllWorkspaces(true)
  window.once('ready-to-show', () => {
    sizeAndPositionIsland(window, { width: 76, height: 8 })
    window.showInactive()
  })
  loadSurface(window, 'island')
  return window
}

function petPreferencesPath(): string {
  return join(stateDir(), 'pet.json')
}

function loadPetPreferences(): PetPreferences {
  try {
    return normalizePetPreferences(JSON.parse(readFileSync(petPreferencesPath(), 'utf8')))
  } catch {
    return { ...DEFAULT_PET_PREFERENCES }
  }
}

function savePetPreferences(): void {
  mkdirSync(stateDir(), { recursive: true })
  writeFileSync(petPreferencesPath(), `${JSON.stringify(petPreferences, null, 2)}\n`, 'utf8')
}

function setPetEnabled(enabled: boolean): void {
  petPreferences = { ...petPreferences, enabled }
  savePetPreferences()
  syncPetWindow()
  refreshTrayMenu()
}

function selectedPetDisplay(): Electron.Display {
  return (
    screen.getAllDisplays().find((display) => display.id === petPreferences.displayId) ??
    (petBounds ? screen.getDisplayMatching(petBounds) : screen.getPrimaryDisplay())
  )
}

function ensurePetHost(): NativePetHost {
  petHost ??= new NativePetHost(
    resolvePetHostPaths(app),
    ({ code, signal }) => {
      desktop.warn('native pet host exited unexpectedly', { code, signal })
      if (isQuitting || !petPreferences.enabled || petRestartTimer) return
      petRestartTimer = setTimeout(() => {
        petRestartTimer = null
        syncPetWindow()
      }, 1_000)
    },
    (level, message) => {
      if (level === 'warning') desktop.warn(message)
      else desktop.info(message)
    },
    (action) => {
      desktop.info('native pet control selected', { action })
      navigateMainWindow(petActionPage(action))
    },
    ({ x, y }) => {
      if (!petBounds || !petPreferences.enabled) return
      const candidate = { ...petBounds, x, y }
      const display = screen.getDisplayMatching(candidate)
      petPreferences = {
        ...petPreferences,
        displayId: display.id,
        position: { x, y }
      }
      petBounds = petWindowBounds(display.workArea, petPreferences)
      petPreferences.position = { x: petBounds.x, y: petBounds.y }
      savePetPreferences()
      petHost?.send({ type: 'bounds', ...petBounds })
      desktop.info('native pet moved', { x: petBounds.x, y: petBounds.y, displayId: display.id })
    }
  )
  return petHost
}

function syncPetWindow(): void {
  if (!petPreferences.enabled) {
    if (petRestartTimer) clearTimeout(petRestartTimer)
    petRestartTimer = null
    petHost?.stop()
    petBounds = null
    return
  }
  petBounds = petWindowBounds(selectedPetDisplay().workArea, petPreferences)
  ensurePetHost().start(petBounds, runtimeStatus.assistant.phase)
}

function startPetCursorPolling(): void {
  let lastDirection: number | null | undefined
  let lastHover: boolean | undefined
  petCursorPoll = setInterval(() => {
    if (!petHost?.running || !petBounds) return
    const cursor = screen.getCursorScreenPoint()
    const hover = pointInBounds(petBounds, cursor)
    if (hover !== lastHover) {
      lastHover = hover
      petHost.send({ type: 'hover', hover })
    }
    const phase = runtimeStatus.assistant.phase
    const canLook = phase === 'ready' || phase === 'listening' || phase === 'speaking'
    const direction = canLook ? petLookDirection(petSpriteBounds(petBounds), cursor) : null
    if (direction === lastDirection) return
    lastDirection = direction
    petHost.send({ type: 'look', direction })
  }, 100)
}

function showMainWindow(): void {
  if (islandWindow && !islandWindow.isDestroyed()) islandWindow.showInactive()
  if (!mainWindow || mainWindow.isDestroyed()) mainWindow = createMainWindow()
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.show()
  mainWindow.focus()
}

function navigateMainWindow(page: 'Voice' | 'Activity'): void {
  showMainWindow()
  const window = mainWindow
  if (!window || window.isDestroyed()) return
  const send = (): void => window.webContents.send('marvi:navigate', page)
  if (window.webContents.isLoadingMainFrame()) window.webContents.once('did-finish-load', send)
  else send()
}

function publishRuntime(next: RuntimeStatus): RuntimeStatus {
  runtimeStatus = next
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('marvi:runtime-state', next)
  }
  if (islandWindow && !islandWindow.isDestroyed()) {
    islandWindow.webContents.send('marvi:runtime-state', next)
  }
  petHost?.send({
    type: 'state',
    phase: next.assistant.phase,
    taskCount: petTaskCount(next.assistant.phase)
  })
  return next
}

async function gatewayRequest(path: string, init?: RequestInit): Promise<RuntimeStatus> {
  const response = await fetch(`${gateway()}${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...init?.headers },
    signal: AbortSignal.timeout(1_200)
  })
  if (!response.ok) throw new Error(`Gateway returned HTTP ${response.status}`)
  const normalized = normalizeRuntimeStatus(await response.json())
  if (!normalized) throw new Error('Gateway returned an invalid runtime snapshot')
  return normalized
}

/** How many consecutive failed polls before the shell calls the Gateway
 * offline. At a two-second interval this is about ten seconds of silence,
 * which is long enough to ride out a slow moment and short enough that a real
 * crash still surfaces quickly. */
const MISSES_BEFORE_OFFLINE = 5
let missedPolls = 0

async function refreshGatewayRuntime(): Promise<RuntimeStatus> {
  try {
    const gateway = await gatewayRequest('/runtime')
    missedPolls = 0
    // The Gateway owns the assistant state: the agent worker reports its phase
    // through it, so it is the only view that knows whether Marvi is listening.
    //
    // This used to spread the *local* assistant and adopt only yolo,
    // confirmation and roomEvent, so phase, caption, detail and level were
    // frozen at whatever the process started with. That was invisible while the
    // starting state happened to be "ready / Say Marvi" — it looked right by
    // accident. The moment the offline default became an honest "Gateway
    // unavailable", the app showed that forever with a Gateway that was up and
    // answering, which is how it was reported.
    //
    // The exception is a live turn: wake, listening, thinking and speaking are
    // driven by the renderer from LiveKit at a far higher rate than this
    // two-second poll, and adopting the Gateway's slower view would stutter
    // them. Anything else, the Gateway is right.
    return publishRuntime(reconcileRuntimeStatus(runtimeStatus, gateway))
  } catch {
    // One missed poll is not a dead Gateway. Installing a model, hashing a
    // file, or a busy machine can all cost more than the request timeout, and
    // declaring the whole app offline on the first miss put a boot-failure
    // screen over a Gateway that was merely working hard — reported while a
    // 2.4 GB model was downloading.
    missedPolls += 1
    if (missedPolls < MISSES_BEFORE_OFFLINE) return runtimeStatus
    return publishRuntime(withServiceReason(offlineRuntimeFrom(app.getVersion(), runtimeStatus)))
  }
}

/**
 * Say why the Gateway is unreachable, when the supervisor knows.
 *
 * "Marvi Gateway unavailable" is what the boot-failure screen showed while the
 * supervisor was holding the actual answer: `port 8765 is already taken by
 * process 31816`. The status is built from a failed HTTP poll, which knows
 * only that nothing answered, and it never asked the thing watching the
 * process.
 *
 * A poll cannot tell a Gateway that is starting from one that will never
 * start. The supervisor can, and it is two objects away.
 */
function withServiceReason(status: RuntimeStatus): RuntimeStatus {
  const report = serviceReports.find((service) => service.name === 'gateway')
  if (!report || !report.detail) return status
  if (report.state !== 'failed' && report.state !== 'gave up') return status
  return {
    ...status,
    components: {
      ...status.components,
      gateway: { state: 'error', detail: report.detail }
    }
  }
}

function startGatewayPolling(): void {
  void refreshGatewayRuntime()
  gatewayPoll = setInterval(() => void refreshGatewayRuntime(), 2_000)
}

function previewAssistantState(state: AssistantState): void {
  if (!is.dev) return
  const normalized = normalizeRuntimeStatus({ ...runtimeStatus, assistant: state })
  if (normalized) publishRuntime(normalized)
}

function createTray(): Tray {
  const instance = new Tray(nativeImage.createFromPath(trayIcon))
  instance.setToolTip('Marvi OS')
  refreshTrayMenu(instance)
  instance.on('double-click', showMainWindow)
  return instance
}

function refreshTrayMenu(instance = tray): void {
  if (!instance || instance.isDestroyed()) return
  instance.setContextMenu(
    Menu.buildFromTemplate([
      { label: 'Open Marvi OS', click: showMainWindow },
      {
        label: petPreferences.enabled ? 'Hide Desktop Pet' : 'Show Desktop Pet',
        click: () => setPetEnabled(!petPreferences.enabled)
      },
      { type: 'separator' },
      { label: 'Quit', click: () => app.quit() }
    ])
  )
}

// One Marvi, and only one.
//
// Two instances would each start a Gateway on 8765, an agent joining the same
// LiveKit room, and the owned Smart Room sidecar. The second of each fails in a
// way that looks like a bug rather than like a second copy, and both would
// write to the same databases. Electron's lock is the cheapest way to make that
// impossible; the second launch just surfaces the first.
/**
 * The wake word listener runs at login as its own process, and when it hears
 * her name it runs `Marvi.exe --wake`. That one command covers both cases: if
 * Marvi is closed it starts her, and if she is open the single-instance lock
 * hands the argument to the copy already running instead of starting a second.
 *
 * So the listener never has to ask whether Marvi is running -- a question it
 * would have to answer racily, and wrongly during the seconds she is starting.
 */
const WAKE_FLAG = '--wake'

/** Set when the app was launched *by* the wake word, for the renderer to read
 *  once it is ready. A join cannot be requested before there is a window. */
let launchedByWake = process.argv.includes(WAKE_FLAG)

function requestWakeJoin(): void {
  showMainWindow()
  if (mainWindow && !mainWindow.isDestroyed()) {
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.focus()
    mainWindow.webContents.send('marvi:wake-join')
  }
}

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', (_event, argv) => {
    if (argv.includes(WAKE_FLAG)) {
      requestWakeJoin()
      return
    }
    showMainWindow()
    if (mainWindow && !mainWindow.isDestroyed()) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })
  void startApp()
}

function startApp(): void {
  app.whenReady().then(() => {
    app.setAppUserModelId('ai.neuretro.marvi-os')
    petPreferences = loadPetPreferences()

    // Marvi's own pages may use the microphone; nothing else may, and no page
    // gets anything else. There was no handler at all, which leaves the
    // decision to Electron's default and makes a refused microphone
    // indistinguishable from a network failure at the point it is reported.
    //
    // Restricted to the app's own content rather than granted blanket: this is
    // an always-on microphone, and the list of what may open it should be one
    // entry long.
    const allowed = new Set(['media', 'audioCapture'])
    session.defaultSession.setPermissionRequestHandler((contents, permission, done) => {
      done(allowed.has(permission) && isMarviPage(contents.getURL()))
    })
    session.defaultSession.setPermissionCheckHandler(
      (_contents, permission, origin) => allowed.has(permission) && isMarviPage(origin)
    )

    startVoiceStack()

    ipcMain.handle('marvi:get-version', () => app.getVersion())
    ipcMain.handle('marvi:get-build-info', () => ({
      version: app.getVersion(),
      commit: process.env['MARVI_BUILD_COMMIT'] ?? 'development',
      buildTime: process.env['MARVI_BUILD_TIME'] ?? 'development',
      platform: process.platform,
      arch: process.arch,
      updateChannel: getUpdateChannel(updateStateDir(process.env['LOCALAPPDATA']))
    }))
    ipcMain.handle('marvi:get-runtime', () => runtimeStatus)
    ipcMain.handle('marvi:get-voice-session', async () => {
      const response = await fetch(`${gateway()}/livekit/session`, {
        method: 'POST',
        signal: AbortSignal.timeout(2_000)
      })
      if (!response.ok) throw new Error(`Gateway returned HTTP ${response.status}`)
      const value = (await response.json()) as Record<string, unknown>
      if (
        typeof value.url !== 'string' ||
        typeof value.room !== 'string' ||
        typeof value.token !== 'string'
      ) {
        throw new Error('Gateway returned an invalid LiveKit session')
      }
      return { url: value.url, room: value.room, token: value.token }
    })
    ipcMain.handle('marvi:set-voice-session-active', async (_event, active) => {
      try {
        const response = await fetch(`${gateway()}/voice/session-state`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ active: Boolean(active) }),
          signal: AbortSignal.timeout(2_000)
        })
        return response.ok
      } catch {
        desktop.warn('could not report foreground voice session state', {
          active: Boolean(active)
        })
        return false
      }
    })
    ipcMain.handle('marvi:read-aloud', async (_event, text) => {
      if (typeof text !== 'string' || !text.trim()) throw new Error('There is nothing to read')
      desktop.info('Chat Read Aloud requested', { chars: text.length })
      try {
        const response = await fetch(`${gateway()}/speech/read-aloud`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ text }),
          signal: AbortSignal.timeout(300_000)
        })
        const value = (await response.json()) as Record<string, unknown>
        if (!response.ok || (!value.played && !value.cancelled)) {
          throw new Error(String(value.error || `Gateway returned HTTP ${response.status}`))
        }
        desktop.info('Chat Read Aloud completed', {
          cancelled: Boolean(value.cancelled),
          seconds: Number(value.seconds || 0)
        })
        return {
          played: Boolean(value.played),
          cancelled: Boolean(value.cancelled),
          seconds: Number(value.seconds || 0)
        }
      } catch (cause) {
        desktop.warn('Chat Read Aloud failed', {
          error: cause instanceof Error ? cause.message : String(cause)
        })
        throw cause
      }
    })
    ipcMain.handle('marvi:stop-read-aloud', async () => {
      try {
        const response = await fetch(`${gateway()}/speech/stop`, {
          method: 'POST',
          signal: AbortSignal.timeout(2_000)
        })
        if (!response.ok) return false
        const value = (await response.json()) as Record<string, unknown>
        return Boolean(value.stopped)
      } catch (cause) {
        desktop.warn('could not stop Chat Read Aloud', {
          error: cause instanceof Error ? cause.message : String(cause)
        })
        return false
      }
    })
    ipcMain.handle('marvi:get-displays', () =>
      screen.getAllDisplays().map((display, index) => ({
        id: display.id,
        label: display.label || `Display ${index + 1}`,
        primary: display.id === screen.getPrimaryDisplay().id
      }))
    )
    ipcMain.handle('marvi:get-island-placement', () => islandPlacement)
    ipcMain.handle('marvi:set-island-placement', (_event, value) => {
      if (!value || typeof value !== 'object') return islandPlacement
      const candidate = value as Partial<IslandPlacement>
      const displayExists =
        candidate.displayId === null ||
        (typeof candidate.displayId === 'number' &&
          screen.getAllDisplays().some((display) => display.id === candidate.displayId))
      const alignmentIsValid =
        candidate.alignment === 'left' ||
        candidate.alignment === 'center' ||
        candidate.alignment === 'right'
      if (!displayExists || !alignmentIsValid) return islandPlacement
      if (!alignmentIsValid) return islandPlacement
      islandPlacement = {
        displayId: candidate.displayId ?? null,
        alignment: candidate.alignment as IslandPlacement['alignment']
      }
      if (islandWindow && !islandWindow.isDestroyed()) {
        sizeAndPositionIsland(islandWindow, islandContentSize)
      }
      return islandPlacement
    })
    ipcMain.handle('marvi:get-pet-preferences', () => petPreferences)
    ipcMain.handle('marvi:set-pet-preferences', (event, value) => {
      if (!mainWindow || event.sender !== mainWindow.webContents) return petPreferences
      const previous = petPreferences
      const next = normalizePetPreferences(value)
      const displayExists =
        next.displayId === null ||
        screen.getAllDisplays().some((display) => display.id === next.displayId)
      if (!displayExists) next.displayId = null
      const placementChanged =
        next.displayId !== previous.displayId ||
        next.side !== previous.side ||
        next.scale !== previous.scale
      next.position = placementChanged ? null : previous.position
      petPreferences = next
      savePetPreferences()
      syncPetWindow()
      refreshTrayMenu()
      return petPreferences
    })
    ipcMain.handle('marvi:set-yolo', async (_event, yolo) => {
      if (typeof yolo !== 'boolean') return runtimeStatus
      try {
        return publishRuntime(
          await gatewayRequest('/runtime/mode', {
            method: 'PUT',
            body: JSON.stringify({ yolo })
          })
        )
      } catch {
        return publishRuntime(offlineRuntimeFrom(app.getVersion(), runtimeStatus))
      }
    })
    ipcMain.handle('marvi:resolve-confirmation', async (_event, token, decision) => {
      if (typeof token !== 'string' || (decision !== 'approve' && decision !== 'deny')) {
        return runtimeStatus
      }
      // The approval is bound to the arguments the Island actually displayed. Anything
      // else and the Gateway burns the token rather than executing a different action.
      const pending = runtimeStatus.assistant.confirmation
      if (!pending || pending.token !== token) return runtimeStatus
      try {
        const response = await fetch(`${gateway()}/confirmations/${encodeURIComponent(token)}`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ decision, arguments: pending.arguments }),
          signal: AbortSignal.timeout(10_000)
        })
        const body = (await response.json()) as { runtime?: unknown }
        const normalized = normalizeRuntimeStatus(body.runtime)
        return normalized ? publishRuntime(normalized) : await refreshGatewayRuntime()
      } catch {
        // A dead Gateway cannot still own an actionable token. Drop the
        // interactive prompt now instead of waiting for the poll miss budget.
        return publishRuntime(offlineRuntimeFrom(app.getVersion(), runtimeStatus))
      }
    })
    ipcMain.handle('marvi:get-audit', async () => {
      try {
        const response = await fetch(`${gateway()}/audit?limit=100`, {
          signal: AbortSignal.timeout(1_500)
        })
        if (!response.ok) return []
        const body = (await response.json()) as { events?: unknown }
        return Array.isArray(body.events) ? body.events : []
      } catch {
        return []
      }
    })
    ipcMain.handle('marvi:get-update-status', () => {
      const root = findRepoRoot() ?? ''
      const stateDir = updateStateDir(process.env['LOCALAPPDATA'])
      const bootstrap = resolveBootstrap(stateDir)
      return {
        supported: canUpdate(root, bootstrap),
        inProgress: updateInProgress(stateDir),
        channel: getUpdateChannel(stateDir),
        root
      }
    })
    ipcMain.handle('marvi:consume-update-result', () =>
      consumeUpdateResult(updateStateDir(process.env['LOCALAPPDATA']))
    )
    ipcMain.handle('marvi:get-update-channel', () =>
      getUpdateChannel(updateStateDir(process.env['LOCALAPPDATA']))
    )
    ipcMain.handle('marvi:set-update-channel', (_event, channel) => {
      if (channel !== 'release' && channel !== 'nightly') {
        return getUpdateChannel(updateStateDir(process.env['LOCALAPPDATA']))
      }
      return setUpdateChannel(updateStateDir(process.env['LOCALAPPDATA']), channel)
    })
    ipcMain.handle('marvi:check-update', async () => {
      const root = findRepoRoot()
      const stateDir = updateStateDir(process.env['LOCALAPPDATA'])
      const channel = getUpdateChannel(stateDir)
      const bootstrap = resolveBootstrap(stateDir)
      if (!root || !bootstrap || !canUpdate(root, bootstrap)) {
        return {
          channel,
          available: false,
          upToDate: false,
          behindBy: 0,
          commits: [],
          error: 'This installation cannot self-update.'
        }
      }
      return checkForUpdate(root, channel, bootstrap)
    })
    ipcMain.handle('marvi:start-update', () => {
      const root = findRepoRoot()
      if (!root) return false
      const stateDir = updateStateDir(process.env['LOCALAPPDATA'])
      const bootstrap = resolveBootstrap(stateDir)
      const started = startUpdate(
        {
          installRoot: root,
          channel: getUpdateChannel(stateDir),
          desktopPid: process.pid,
          relaunchExe: process.execPath
        },
        bootstrap
      )
      if (started) {
        // The bootstrap waits for this process to exit before touching the
        // checkout, so quitting is part of the handoff, not a side effect.
        isQuitting = true
        setTimeout(() => app.quit(), 250)
      }
      return started
    })
    ipcMain.handle('marvi:get-initiative', async () => {
      try {
        const response = await fetch(`${gateway()}/initiative`, {
          signal: AbortSignal.timeout(2_000)
        })
        if (!response.ok) return null
        return await response.json()
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:set-initiative', async (_event, paused) => {
      if (typeof paused !== 'boolean') return null
      try {
        const response = await fetch(`${gateway()}/initiative`, {
          method: 'PUT',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ paused }),
          signal: AbortSignal.timeout(3_000)
        })
        return response.ok ? await response.json() : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:get-decisions', async () => {
      try {
        const response = await fetch(`${gateway()}/mind/decisions?limit=60`, {
          signal: AbortSignal.timeout(2_000)
        })
        if (!response.ok) return { decisions: [], events: [] }
        return await response.json()
      } catch {
        return { decisions: [], events: [] }
      }
    })
    ipcMain.handle('marvi:get-memory', async () => {
      try {
        const response = await fetch(`${gateway()}/memory?limit=60`, {
          signal: AbortSignal.timeout(2_000)
        })
        if (!response.ok) return { total: 0, entries: [], summary: {} }
        return await response.json()
      } catch {
        return { total: 0, entries: [], summary: {} }
      }
    })
    ipcMain.handle('marvi:get-memory-graph', async (_event, requestedMode) => {
      const mode = requestedMode === 'contacts' ? 'contacts' : 'tree'
      try {
        const response = await fetch(`${gateway()}/arc/memory/graph?mode=${mode}&limit=1000`, {
          signal: AbortSignal.timeout(3_000)
        })
        if (!response.ok) return { mode, nodes: [], edges: [] }
        return await response.json()
      } catch {
        return { mode, nodes: [], edges: [] }
      }
    })
    ipcMain.handle('marvi:clear-memory', async () => {
      try {
        const response = await fetch(`${gateway()}/memory`, {
          method: 'DELETE',
          signal: AbortSignal.timeout(5_000)
        })
        return response.ok
      } catch {
        return false
      }
    })
    ipcMain.handle('marvi:get-accounts', async () => {
      const body = await gatewayJson('/accounts', undefined, 8_000)
      return normaliseAccountPage(
        body ?? { available: false, detail: 'Gateway unavailable', accounts: [] }
      )
    })
    ipcMain.handle('marvi:get-account-catalog', async (): Promise<AccountToolkit[]> => {
      const body = (await gatewayJson('/accounts/catalog?limit=100', undefined, 15_000)) as {
        toolkits?: Array<Record<string, unknown>>
      } | null
      return (body?.toolkits ?? []).map((row) => ({
        slug: String(row.slug ?? ''),
        name: String(row.name ?? row.slug ?? ''),
        description: String(row.description ?? ''),
        logo: String(row.logo ?? ''),
        nativeMemory: Boolean(row.native_memory)
      }))
    })
    ipcMain.handle('marvi:configure-accounts', async (_event, apiKey) => {
      if (typeof apiKey !== 'string' || apiKey.trim().length < 8) {
        return { ok: false, detail: 'Enter a Composio project API key' }
      }
      const body = await gatewayJson(
        '/accounts/config',
        {
          method: 'PUT',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ api_key: apiKey.trim() })
        },
        15_000
      )
      return body
        ? { ok: true, detail: 'Composio connected. Provider credentials stay in Composio.' }
        : { ok: false, detail: 'Composio rejected that project key.' }
    })
    ipcMain.handle('marvi:connect-account', async (_event, toolkit) => {
      if (typeof toolkit !== 'string' || !toolkit) return { ok: false, detail: 'Choose an account' }
      const body = (await gatewayJson('/accounts/connect', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ toolkit })
      })) as { redirect_url?: string } | null
      const url = String(body?.redirect_url ?? '')
      if (!isComposioConnectUrl(url)) return { ok: false, detail: 'Invalid authorization URL' }
      await shell.openExternal(url)
      return { ok: true, detail: 'Finish authorization in your browser' }
    })
    ipcMain.handle('marvi:refresh-account', async (_event, connectionId) => {
      if (typeof connectionId !== 'string' || !connectionId) {
        return { ok: false, detail: 'Missing connection' }
      }
      const body = (await gatewayJson(`/accounts/${encodeURIComponent(connectionId)}/refresh`, {
        method: 'POST'
      })) as { redirect_url?: string } | null
      const url = String(body?.redirect_url ?? '')
      if (url && isComposioConnectUrl(url)) {
        await shell.openExternal(url)
        return { ok: true, detail: 'Finish reconnecting in your browser' }
      }
      return { ok: body !== null, detail: body ? 'Connection refreshed' : 'Refresh failed' }
    })
    ipcMain.handle('marvi:set-account-enabled', async (_event, connectionId, enabled) => {
      if (typeof connectionId !== 'string' || typeof enabled !== 'boolean') return false
      return (
        (await gatewayJson(`/accounts/${encodeURIComponent(connectionId)}/enabled`, {
          method: 'PUT',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ enabled })
        })) !== null
      )
    })
    ipcMain.handle('marvi:delete-account', async (_event, connectionId) => {
      if (typeof connectionId !== 'string' || !connectionId) return false
      return (
        (await gatewayJson(`/accounts/${encodeURIComponent(connectionId)}`, {
          method: 'DELETE'
        })) !== null
      )
    })
    ipcMain.handle('marvi:set-account-policy', async (_event, toolkit, update) => {
      if (typeof toolkit !== 'string' || typeof update !== 'object' || update === null) return false
      const safe: Record<string, unknown> = {}
      if (update.scope === 'read' || update.scope === 'write' || update.scope === 'admin') {
        safe.scope = update.scope
      }
      if (typeof update.sync_enabled === 'boolean') safe.sync_enabled = update.sync_enabled
      return (
        (await gatewayJson(`/accounts/policy/${encodeURIComponent(toolkit)}`, {
          method: 'PUT',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(safe)
        })) !== null
      )
    })
    ipcMain.handle('marvi:sync-account', async (_event, toolkit, connectionId) => {
      const payload = {
        toolkit: typeof toolkit === 'string' && toolkit ? toolkit : null,
        connection_id: typeof connectionId === 'string' && connectionId ? connectionId : null
      }
      return (
        (await gatewayJson(
          '/accounts/sync',
          {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(payload)
          },
          60_000
        )) !== null
      )
    })
    // Capabilities > Connectors. Deliberately separate from the `/accounts`
    // block above: that route stays alive for compatibility, but the
    // renderer's Connectors grid speaks the newer, simpler `/connectors`
    // contract (status + connection count per slug, no sync/trigger state).
    ipcMain.handle('marvi:get-connectors', async (): Promise<ConnectorsPage> => {
      const body = await gatewayJson('/connectors', undefined, 8_000)
      return normaliseConnectorsPage(body ?? { available: false, connectors: [] })
    })
    ipcMain.handle('marvi:connect-connector', async (_event, slug) => {
      if (typeof slug !== 'string' || !slug) return { ok: false, detail: 'Choose a connector' }
      const body = (await gatewayJson(`/connectors/${encodeURIComponent(slug)}/connect`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' }
      })) as { connect_url?: string; connection_id?: string } | null
      const url = String(body?.connect_url ?? '')
      if (!isSafeConnectUrl(url)) return { ok: false, detail: 'Invalid authorization URL' }
      await shell.openExternal(url)
      return {
        ok: true,
        detail: 'Finish authorization in your browser',
        connectionId: body?.connection_id ?? ''
      }
    })
    ipcMain.handle(
      'marvi:get-connector-status',
      async (_event, slug): Promise<ConnectorRow | null> => {
        if (typeof slug !== 'string' || !slug) return null
        const body = await gatewayJson(`/connectors/${encodeURIComponent(slug)}`, undefined, 8_000)
        return body ? normaliseConnectorRow(body) : null
      }
    )
    ipcMain.handle('marvi:set-connector-scope', async (_event, slug, scope) => {
      if (typeof slug !== 'string' || !slug) return false
      if (scope !== 'read' && scope !== 'write' && scope !== 'admin') return false
      return (
        (await gatewayJson(`/connectors/${encodeURIComponent(slug)}/scope`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ scope })
        })) !== null
      )
    })
    ipcMain.handle('marvi:disconnect-connector', async (_event, connectionId) => {
      if (typeof connectionId !== 'string' || !connectionId) return false
      return (
        (await gatewayJson(`/connectors/connections/${encodeURIComponent(connectionId)}`, {
          method: 'DELETE'
        })) !== null
      )
    })

    // Capabilities > MCP. `marvi:get-mcp` above hits the older, unshaped
    // `/mcp` route and is kept only because nothing has migrated off it yet;
    // these speak the servers/registry/install contract the MCP page renders.
    ipcMain.handle('marvi:get-mcp-servers', async (): Promise<McpServersPage | null> => {
      const body = (await gatewayJson('/mcp/servers', undefined, 8_000)) as {
        servers?: Array<Record<string, unknown>>
      } | null
      if (!body) return null
      return {
        servers: (body.servers ?? []).map((row) => ({
          id: String(row.id ?? ''),
          name: String(row.name ?? row.id ?? ''),
          status: String(row.status ?? 'unknown'),
          tools: Number(row.tools ?? 0),
          source: 'installed' as const
        }))
      }
    })
    ipcMain.handle(
      'marvi:get-mcp-registry',
      async (_event, query, page): Promise<McpRegistryPage | null> => {
        const q = typeof query === 'string' ? query : ''
        const p = typeof page === 'number' && page > 0 ? page : 1
        const body = (await gatewayJson(
          `/mcp/registry?q=${encodeURIComponent(q)}&page=${p}`,
          undefined,
          15_000
        )) as { servers?: Array<Record<string, unknown>>; total_pages?: number } | null
        if (!body) return null
        return {
          servers: (body.servers ?? []).map((row) => ({
            qualifiedName: String(row.qualified_name ?? ''),
            name: String(row.name ?? row.qualified_name ?? ''),
            description: String(row.description ?? ''),
            author: String(row.author ?? ''),
            source: 'registry' as const
          })),
          totalPages: Number(body.total_pages ?? 1)
        }
      }
    )
    ipcMain.handle('marvi:install-mcp-server', async (_event, qualifiedName, env) => {
      if (typeof qualifiedName !== 'string' || !qualifiedName) {
        return { ok: false, detail: 'Choose a server to install' }
      }
      const safeEnv: Record<string, string> = {}
      if (env && typeof env === 'object') {
        for (const [key, value] of Object.entries(env as Record<string, unknown>)) {
          if (typeof value === 'string') safeEnv[key] = value
        }
      }
      const body = await gatewayJson(
        '/mcp/install',
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ qualified_name: qualifiedName, env: safeEnv })
        },
        20_000
      )
      return body
        ? { ok: true, detail: 'Installed' }
        : { ok: false, detail: 'The MCP registry could not install that server.' }
    })
    ipcMain.handle('marvi:delete-mcp-server', async (_event, id) => {
      if (typeof id !== 'string' || !id) return false
      return (
        (await gatewayJson(`/mcp/servers/${encodeURIComponent(id)}`, { method: 'DELETE' })) !== null
      )
    })

    ipcMain.handle('marvi:get-schedules', () => gatewayJson('/schedules'))
    ipcMain.handle('marvi:add-schedule', (_event, body) =>
      gatewayJson('/schedules', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body)
      })
    )
    ipcMain.handle('marvi:schedule-action', (_event, id, action) =>
      gatewayJson(
        `/schedules/${encodeURIComponent(String(id))}/${encodeURIComponent(String(action))}`,
        { method: 'POST' }
      )
    )
    ipcMain.handle('marvi:get-plugins', () => gatewayJson('/plugins'))
    // A clone plus a dependency install. Minutes, not seconds.
    ipcMain.handle('marvi:plugin-action', (_event, name, action) =>
      gatewayJson(
        `/plugins/${encodeURIComponent(String(name))}/${encodeURIComponent(String(action))}`,
        { method: 'POST' },
        20 * 60_000
      )
    )
    ipcMain.handle('marvi:get-setup', () => gatewayJson('/setup'))
    ipcMain.handle('marvi:get-hardware', () => gatewayJson('/setup/hardware'))
    ipcMain.handle('marvi:set-hardware', (_event, useGpu) =>
      gatewayJson('/setup/hardware', {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ use_gpu: Boolean(useGpu) })
      })
    )
    ipcMain.handle('marvi:install-component', (_event, name) =>
      // Gigabytes: the timeout has to allow for a real download on a real line.
      gatewayJson(
        `/setup/${encodeURIComponent(String(name))}/install`,
        { method: 'POST' },
        1_800_000
      )
    )
    ipcMain.handle('marvi:remove-component', (_event, name) =>
      gatewayJson(`/setup/${encodeURIComponent(String(name))}/remove`, { method: 'POST' })
    )
    ipcMain.handle('marvi:get-skill-store', () => gatewayJson('/skills/store', undefined, 60_000))
    ipcMain.handle('marvi:review-skill', (_event, repo, path) =>
      gatewayJson(
        '/skills/review',
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ repo, path })
        },
        60_000
      )
    )
    ipcMain.handle('marvi:install-skill', (_event, staged) =>
      gatewayJson('/skills/install', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ staged })
      })
    )
    ipcMain.handle('marvi:remove-skill', (_event, name) =>
      gatewayJson(`/skills/${encodeURIComponent(String(name))}`, { method: 'DELETE' })
    )
    ipcMain.handle('marvi:get-installed-skills', async () => {
      const body = await gatewayJson('/skills')
      if (!isRecord(body)) return null
      const rows = Array.isArray(body.skills) ? body.skills.filter(isRecord) : []
      return {
        skills: rows.map((row) => {
          const usage = isRecord(row.usage) ? row.usage : {}
          return {
            name: String(row.name ?? ''),
            description: String(row.description ?? ''),
            source: String(row.source ?? ''),
            platforms: Array.isArray(row.platforms) ? row.platforms.map(String) : [],
            requires: Array.isArray(row.requires) ? row.requires.map(String) : [],
            applies: row.applies !== false,
            usage: {
              uses: Number(usage.uses ?? 0),
              lastUsed: String(usage.last_used ?? ''),
              mine: usage.mine === true,
              pinned: usage.pinned === true,
              state: usage.state === 'stale' || usage.state === 'archived' ? usage.state : 'active'
            }
          }
        }),
        archived: Array.isArray(body.archived) ? body.archived.map(String) : [],
        trustedSources: Array.isArray(body.trusted_sources) ? body.trusted_sources.map(String) : [],
        trustedSetting: String(body.trusted_setting ?? '')
      }
    })
    ipcMain.handle('marvi:pin-skill', (_event, name, pinned) =>
      gatewayJson(`/skills/${encodeURIComponent(String(name))}/pin`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ pinned: pinned === true })
      })
    )
    ipcMain.handle('marvi:archive-skill', (_event, name) =>
      gatewayJson(`/skills/${encodeURIComponent(String(name))}/archive`, { method: 'POST' })
    )
    ipcMain.handle('marvi:restore-skill', (_event, name) =>
      gatewayJson(`/skills/${encodeURIComponent(String(name))}/restore`, { method: 'POST' })
    )
    ipcMain.handle('marvi:get-mcp', () => gatewayJson('/mcp'))
    ipcMain.handle('marvi:run-doctor', async () => {
      try {
        const response = await fetch(`${gateway()}/doctor`, {
          signal: AbortSignal.timeout(20_000)
        })
        return response.ok ? await response.json() : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:heal-doctor', async (_event, includeConfirmed) => {
      try {
        const response = await fetch(`${gateway()}/doctor/heal`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ include_confirmed: Boolean(includeConfirmed) }),
          signal: AbortSignal.timeout(120_000)
        })
        return response.ok ? await response.json() : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:copy-text', (_event, value) => {
      if (typeof value !== 'string' || value.length > 1_000_000) return false
      clipboard.writeText(value)
      return true
    })
    ipcMain.handle('marvi:open-maintenance-terminal', async (_event, action) => {
      if (process.platform !== 'win32') return false
      const root = repoRoot ?? findRepoRoot()
      const uv = findUv()
      const project = root ? join(root, 'services', 'gateway') : ''
      const args = maintenancePowerShellArgs(action, uv ?? '', project)
      if (!args || !root || !uv) {
        desktop.warn('maintenance terminal could not resolve its runtime', {
          action: String(action),
          repo: Boolean(root),
          uv: Boolean(uv)
        })
        return false
      }
      const powershell = join(
        process.env['SystemRoot'] || 'C:\\Windows',
        'System32',
        'WindowsPowerShell',
        'v1.0',
        'powershell.exe'
      )
      try {
        const terminal = spawn(powershell, args, {
          cwd: root,
          detached: true,
          stdio: 'ignore',
          windowsHide: false
        })
        return await new Promise<boolean>((resolveLaunch) => {
          terminal.once('spawn', () => {
            terminal.unref()
            desktop.info('maintenance terminal opened', { action: String(action) })
            resolveLaunch(true)
          })
          terminal.once('error', (cause) => {
            desktop.warn('maintenance terminal failed to open', {
              action: String(action),
              error: cause.message
            })
            resolveLaunch(false)
          })
        })
      } catch (cause) {
        desktop.warn('maintenance terminal failed to open', {
          action: String(action),
          error: cause instanceof Error ? cause.message : String(cause)
        })
        return false
      }
    })
    ipcMain.handle('marvi:copy-diagnostics', async () => {
      try {
        const response = await fetch(`${gateway()}/doctor/diagnostics`, {
          signal: AbortSignal.timeout(20_000)
        })
        if (!response.ok) return null
        return ((await response.json()) as { text?: string }).text ?? null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:get-logs', async (_event, subsystem) => {
      const name = typeof subsystem === 'string' && subsystem ? subsystem : 'errors'
      try {
        const response = await fetch(`${gateway()}/logs?subsystem=${encodeURIComponent(name)}`, {
          signal: AbortSignal.timeout(8_000)
        })
        return response.ok ? await response.json() : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:get-chat', async (_event, threadId) => {
      try {
        const query =
          typeof threadId === 'string' && threadId
            ? `?thread_id=${encodeURIComponent(threadId)}`
            : ''
        const response = await fetch(`${gateway()}/chat${query}`, {
          signal: AbortSignal.timeout(4_000)
        })
        return response.ok
          ? await response.json()
          : { messages: [], available: false, threads: [], active_thread: 'default' }
      } catch {
        return { messages: [], available: false, threads: [], active_thread: 'default' }
      }
    })
    ipcMain.handle('marvi:get-chat-threads', async (_event, archived) => {
      try {
        const response = await fetch(`${gateway()}/chat/threads?archived=${archived === true}`, {
          signal: AbortSignal.timeout(4_000)
        })
        const body = response.ok ? ((await response.json()) as { threads?: unknown }) : null
        return Array.isArray(body?.threads) ? body.threads : []
      } catch {
        return []
      }
    })
    ipcMain.handle('marvi:create-chat-thread', async (_event, title) => {
      try {
        const response = await fetch(`${gateway()}/chat/threads`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ title: typeof title === 'string' ? title : 'New conversation' }),
          signal: AbortSignal.timeout(4_000)
        })
        return response.ok ? await response.json() : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:update-chat-thread', async (_event, id, update) => {
      if (typeof id !== 'string') return null
      try {
        const response = await fetch(`${gateway()}/chat/threads/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(update ?? {}),
          signal: AbortSignal.timeout(4_000)
        })
        return response.ok ? await response.json() : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:set-chat-thread-model', async (_event, id, selection) => {
      if (typeof id !== 'string') return null
      const pick = (key: string): string =>
        typeof selection?.[key] === 'string' ? selection[key].trim() : ''
      try {
        const response = await fetch(`${gateway()}/chat/threads/${encodeURIComponent(id)}/model`, {
          method: 'PUT',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            provider: pick('provider'),
            model: pick('model'),
            effort: pick('effort')
          }),
          signal: AbortSignal.timeout(5_000)
        })
        return response.ok ? await response.json() : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:delete-chat-thread', async (_event, id) => {
      if (typeof id !== 'string') return false
      try {
        const response = await fetch(`${gateway()}/chat/threads/${encodeURIComponent(id)}`, {
          method: 'DELETE',
          signal: AbortSignal.timeout(5_000)
        })
        if (!response.ok) return false
        const value = (await response.json()) as { removed?: unknown }
        return typeof value.removed === 'number'
      } catch {
        return false
      }
    })
    ipcMain.handle('marvi:upload-chat-attachment', async (_event, input) => {
      if (!input || typeof input !== 'object') return null
      try {
        const response = await fetch(`${gateway()}/chat/attachments`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            thread_id: input.threadId,
            name: input.name,
            media_type: input.mediaType,
            data: input.data
          }),
          signal: AbortSignal.timeout(30_000)
        })
        return response.ok ? await response.json() : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:remove-chat-attachment', async (_event, id) => {
      if (typeof id !== 'string') return false
      try {
        const response = await fetch(`${gateway()}/chat/attachments/${encodeURIComponent(id)}`, {
          method: 'DELETE',
          signal: AbortSignal.timeout(5_000)
        })
        return response.ok
      } catch {
        return false
      }
    })
    ipcMain.handle('marvi:get-chat-attachment', async (_event, id) => {
      if (typeof id !== 'string') return null
      try {
        const response = await fetch(`${gateway()}/chat/attachments/${encodeURIComponent(id)}`, {
          signal: AbortSignal.timeout(5_000)
        })
        if (!response.ok) return null
        const body = (await response.json()) as { media_type?: unknown; data?: unknown }
        return typeof body.media_type === 'string' && typeof body.data === 'string'
          ? { mediaType: body.media_type, data: body.data }
          : null
      } catch {
        return null
      }
    })
    // At most one turn in flight. A second message supersedes the first
    // rather than racing it into the same window, and aborting closes the
    // socket -- which the Gateway sees, and passes on to the provider.
    let inFlight: AbortController | null = null

    ipcMain.handle('marvi:cancel-chat', () => {
      inFlight?.abort()
      inFlight = null
      return true
    })

    ipcMain.handle('marvi:stream-chat', async (event, message, override, context) => {
      if (typeof message !== 'string') return false
      inFlight?.abort()
      const controller = new AbortController()
      inFlight = controller
      const pick = (key: string): string | undefined =>
        typeof override?.[key] === 'string' && override[key] ? override[key] : undefined

      // A turn is pushed as it happens rather than returned when it is over,
      // because an IPC handler resolves once and streaming is the opposite of
      // that. Each event goes straight to the window that asked for it.
      const send = (payload: unknown): void => {
        if (!event.sender.isDestroyed()) event.sender.send('marvi:chat-delta', payload)
      }

      try {
        const response = await fetch(`${gateway()}/chat/stream`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            message,
            provider: pick('provider'),
            model: pick('model'),
            effort: pick('effort'),
            thread_id: typeof context?.threadId === 'string' ? context.threadId : 'default',
            attachment_ids: Array.isArray(context?.attachmentIds) ? context.attachmentIds : [],
            edit_message_id:
              typeof context?.editMessageId === 'number' ? context.editMessageId : undefined,
            regenerate_message_id:
              typeof context?.regenerateMessageId === 'number'
                ? context.regenerateMessageId
                : undefined
          }),
          // No timeout. A tool round can be slow and the turn reports its own
          // completion; cutting the socket mid-answer would look like Marvi
          // stopping mid-sentence. Cancellation is deliberate, not a clock.
          signal: controller.signal
        })
        if (!response.ok || !response.body) {
          send({ done: true, error: `the Gateway refused the turn (${response.status})` })
          return false
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        for (;;) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          // SSE frames are separated by a blank line, and a chunk can split
          // one anywhere, so whatever trails the last separator is kept.
          const frames = buffer.split(SSE_FRAME_SEPARATOR)
          buffer = frames.pop() ?? ''
          for (const frame of frames) {
            const line = frame.trim()
            if (!line.startsWith('data:')) continue
            try {
              send(JSON.parse(line.slice(5).trim()))
            } catch {
              // A frame that will not parse is not worth ending a turn over.
            }
          }
        }
        return true
      } catch (cause) {
        if (controller.signal.aborted) {
          // Asked for. Not a failure, and not worth an error in the window.
          send({ done: true, cancelled: true, error: '' })
          return true
        }
        send({ done: true, error: cause instanceof Error ? cause.message : String(cause) })
        return false
      } finally {
        if (inFlight === controller) inFlight = null
      }
    })
    ipcMain.handle('marvi:send-chat', async (_event, message, override) => {
      if (typeof message !== 'string') return null
      // Sent per turn and stored nowhere. The composer's picker is "try this
      // model on this conversation", not "change the default for voice, mind
      // and vision too".
      const pick = (key: string): string | undefined =>
        typeof override?.[key] === 'string' && override[key] ? override[key] : undefined
      try {
        const response = await fetch(`${gateway()}/chat`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            message,
            provider: pick('provider'),
            model: pick('model'),
            effort: pick('effort')
          }),
          // A tool round trip can be slow; a short timeout would look like a bug.
          signal: AbortSignal.timeout(180_000)
        })
        return response.ok ? await response.json() : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:clear-chat', async (_event, threadId) => {
      try {
        const query =
          typeof threadId === 'string' && threadId
            ? `?thread_id=${encodeURIComponent(threadId)}`
            : ''
        const response = await fetch(`${gateway()}/chat${query}`, {
          method: 'DELETE',
          signal: AbortSignal.timeout(5_000)
        })
        return response.ok
      } catch {
        return false
      }
    })
    ipcMain.handle('marvi:start-chat-dictation', async (_event, language) => {
      try {
        const response = await fetch(`${gateway()}/chat/dictation`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ language: typeof language === 'string' ? language : 'en-US' }),
          signal: AbortSignal.timeout(180_000)
        })
        if (!response.ok) throw await gatewayFailure(response, 'Dictation could not start')
        return await response.json()
      } catch (cause) {
        desktop.warn('Chat dictation could not start', {
          error: cause instanceof Error ? cause.message : String(cause)
        })
        throw cause
      }
    })
    ipcMain.handle('marvi:push-chat-dictation-audio', async (_event, id, pcm16) => {
      if (typeof id !== 'string' || typeof pcm16 !== 'string') return null
      try {
        const response = await fetch(
          `${gateway()}/chat/dictation/${encodeURIComponent(id)}/audio`,
          {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ pcm16 }),
            signal: AbortSignal.timeout(30_000)
          }
        )
        return response.ok ? await response.json() : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:stop-chat-dictation', async (_event, id) => {
      if (typeof id !== 'string') return null
      try {
        const response = await fetch(`${gateway()}/chat/dictation/${encodeURIComponent(id)}/stop`, {
          method: 'POST',
          signal: AbortSignal.timeout(30_000)
        })
        return response.ok ? await response.json() : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:cancel-chat-dictation', async (_event, id) => {
      if (typeof id !== 'string') return false
      try {
        const response = await fetch(`${gateway()}/chat/dictation/${encodeURIComponent(id)}`, {
          method: 'DELETE',
          signal: AbortSignal.timeout(5_000)
        })
        return response.ok
      } catch {
        return false
      }
    })
    ipcMain.handle('marvi:get-services', () => serviceReports)
    ipcMain.handle('marvi:retry-service', (_event, name) => {
      if (typeof name !== 'string' || !supervisor) return false
      return supervisor.retry(name)
    })
    ipcMain.handle('marvi:get-providers', async () => {
      try {
        const response = await fetch(`${gateway()}/providers`, {
          signal: AbortSignal.timeout(5_000)
        })
        if (!response.ok) return null
        return normaliseProviderPage(await response.json())
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:get-usage', async (_event, refresh = true) => {
      try {
        const response = await fetch(`${gateway()}/usage?refresh=${refresh ? 'true' : 'false'}`, {
          signal: AbortSignal.timeout(refresh ? 12_000 : 5_000)
        })
        return response.ok ? normaliseUsagePage(await response.json()) : null
      } catch {
        return null
      }
    })
    // The two cards beside the orb. Both go through here rather than fetching
    // from the renderer, because everything else on this page does and a
    // second way to reach the Gateway is a second thing to keep in step with
    // the port, the token and the CSP.
    ipcMain.handle('marvi:get-voice-activity', async () => {
      try {
        const response = await fetch(`${gateway()}/voice/activity`, {
          signal: AbortSignal.timeout(4_000)
        })
        return response.ok ? await response.json() : null
      } catch {
        return null
      }
    })

    ipcMain.handle('marvi:get-calendar', async () => {
      try {
        const response = await fetch(`${gateway()}/calendar/upcoming?limit=8`, {
          // Longer than the others: this one goes out to Google through
          // Composio, and a card that gives up at four seconds shows "not
          // connected" over a calendar that is merely slow.
          signal: AbortSignal.timeout(15_000)
        })
        return response.ok ? await response.json() : null
      } catch {
        return null
      }
    })

    ipcMain.handle('marvi:get-wake', async (): Promise<WakeStatus | null> => {
      try {
        const response = await fetch(`${gateway()}/voice/wake`, {
          signal: AbortSignal.timeout(5_000)
        })
        if (!response.ok) return null
        const body = (await response.json()) as Record<string, never>
        return {
          enabled: Boolean(body.enabled),
          model: String(body.model ?? ''),
          modelPresent: Boolean(body.model_present),
          armed: Boolean(body.armed),
          threshold: Number(body.threshold ?? 0.5),
          heardSecondsAgo:
            body.heard_seconds_ago === null || body.heard_seconds_ago === undefined
              ? null
              : Number(body.heard_seconds_ago),
          recentlyHeard: Boolean(body.recently_heard),
          confidence: Number(body.confidence ?? 0),
          setting: String(body.setting ?? 'MARVI_WAKE_WORD'),
          thresholdSetting: String(body.threshold_setting ?? 'MARVI_WAKE_THRESHOLD'),
          device: String(body.device ?? ''),
          deviceSetting: String(body.device_setting ?? 'MARVI_WAKE_DEVICE'),
          devices: Array.isArray(body.devices)
            ? (body.devices as Record<string, unknown>[]).map((entry) => ({
                name: String(entry['name'] ?? ''),
                label: String(entry['label'] ?? entry['name'] ?? ''),
                default: Boolean(entry['default'])
              }))
            : [],
          listener: {
            autostart: Boolean((body.listener as Record<string, unknown>)?.['autostart']),
            running: Boolean((body.listener as Record<string, unknown>)?.['running']),
            error: String((body.listener as Record<string, unknown>)?.['error'] ?? ''),
            silentFor:
              (body.listener as Record<string, unknown>)?.['silent_for'] === null ||
              (body.listener as Record<string, unknown>)?.['silent_for'] === undefined
                ? null
                : Number((body.listener as Record<string, unknown>)['silent_for']),
            everRan: Boolean((body.listener as Record<string, unknown>)?.['ever_ran'])
          }
        }
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:consume-wake-launch', () => {
      // Consumed rather than read: the renderer reloads on navigation, and a
      // flag that stayed set would rejoin the room every time it did.
      const was = launchedByWake
      launchedByWake = false
      return was
    })
    ipcMain.handle('marvi:get-wake-autostart', async () => wakeAutostart('status'))
    ipcMain.handle('marvi:set-wake-autostart', async (_event, enabled, device) => {
      if (typeof enabled !== 'boolean') return wakeAutostart('status')
      return wakeAutostart(enabled ? 'enable' : 'disable', typeof device === 'string' ? device : '')
    })
    ipcMain.handle('marvi:get-voices', async (): Promise<VoicePage | null> => {
      try {
        const response = await fetch(`${gateway()}/voices`, {
          signal: AbortSignal.timeout(5_000)
        })
        if (!response.ok) return null
        const body = (await response.json()) as Record<string, never>
        const rows = Array.isArray(body.voices) ? (body.voices as Array<Record<string, never>>) : []
        const engines = Array.isArray(body.engines)
          ? (body.engines as Array<Record<string, never>>)
          : []
        return {
          engineSetting: String(body.engine_setting ?? ''),
          selectedEngine: String(body.selected_engine ?? ''),
          engineMissing: Boolean(body.engine_missing),
          setting: String(body.setting ?? ''),
          selected: String(body.selected ?? ''),
          missing: Boolean(body.missing),
          engines: engines.map((row) => ({
            id: String(row.id ?? ''),
            name: String(row.name ?? ''),
            description: String(row.description ?? ''),
            runtime: String(row.runtime ?? ''),
            defaultVoice: String(row.default_voice ?? ''),
            cloning: Boolean(row.cloning),
            available: Boolean(row.available)
          })),
          voices: rows.map((row) => ({
            id: String(row.id ?? ''),
            name: String(row.name ?? ''),
            language: String(row.language ?? ''),
            gender: String(row.gender ?? ''),
            cloned: Boolean(row.cloned)
          }))
        }
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:get-voice-clones', async (): Promise<VoiceClonePage | null> => {
      try {
        const response = await fetch(`${gateway()}/voices/clones`, {
          signal: AbortSignal.timeout(5_000)
        })
        if (!response.ok) return null
        const body = (await response.json()) as Record<string, never>
        const rows = Array.isArray(body.clones) ? (body.clones as Array<Record<string, never>>) : []
        return {
          engines: Array.isArray(body.engines) ? (body.engines as string[]).map(String) : [],
          shortestSeconds: Number(body.shortest_seconds ?? 0),
          longestSeconds: Number(body.longest_seconds ?? 0),
          clones: rows.map((row) => ({
            id: String(row.id ?? ''),
            name: String(row.name ?? ''),
            engine: String(row.engine ?? ''),
            seconds: Number(row.seconds ?? 0)
          }))
        }
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:add-voice-clone', async (_event, engine, name) => {
      if (typeof engine !== 'string' || typeof name !== 'string') {
        return { ok: false, detail: 'bad request' }
      }
      // The native picker, and the file is read here rather than in the
      // renderer: the renderer has no filesystem, and routing a recording
      // through a drag-and-drop payload would be a second way in for the same
      // thing.
      const chosen = await dialog.showOpenDialog({
        title: 'Choose a recording of the voice',
        filters: [{ name: 'Recording', extensions: ['wav'] }],
        properties: ['openFile']
      })
      if (chosen.canceled || !chosen.filePaths[0]) return { ok: false, detail: '' }
      try {
        const audio = await readFile(chosen.filePaths[0])
        const response = await fetch(`${gateway()}/voices/clones`, {
          method: 'POST',
          headers: { 'content-type': 'application/json', ...localHeaders() },
          body: JSON.stringify({ engine, name, audio: audio.toString('base64') }),
          signal: AbortSignal.timeout(30_000)
        })
        if (!response.ok) return { ok: false, detail: 'the Gateway refused' }
        const body = (await response.json()) as Record<string, never>
        return { ok: Boolean(body.ok), detail: String(body.detail ?? '') }
      } catch (error) {
        return { ok: false, detail: String(error) }
      }
    })
    ipcMain.handle('marvi:remove-voice-clone', async (_event, engine, voice) => {
      if (typeof engine !== 'string' || typeof voice !== 'string') return false
      try {
        const response = await fetch(
          `${gateway()}/voices/clones/${encodeURIComponent(engine)}/${encodeURIComponent(voice)}`,
          {
            method: 'DELETE',
            headers: localHeaders(),
            signal: AbortSignal.timeout(10_000)
          }
        )
        if (!response.ok) return false
        const body = (await response.json()) as Record<string, never>
        return Boolean(body.ok)
      } catch {
        return false
      }
    })
    ipcMain.handle('marvi:get-recognisers', async (): Promise<RecogniserPage | null> => {
      try {
        const response = await fetch(`${gateway()}/recognisers`, {
          signal: AbortSignal.timeout(5_000)
        })
        if (!response.ok) return null
        const body = (await response.json()) as Record<string, never>
        const rows = Array.isArray(body.engines) ? (body.engines as Array<Record<string, never>>) : []
        return {
          setting: String(body.setting ?? ''),
          selected: String(body.selected ?? ''),
          missing: Boolean(body.missing),
          engines: rows.map((row) => ({
            id: String(row.id ?? ''),
            name: String(row.name ?? ''),
            description: String(row.description ?? ''),
            runtime: String(row.runtime ?? ''),
            available: Boolean(row.available),
            measured: (row.measured ?? {}) as RecogniserPage['engines'][number]['measured']
          }))
        }
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:connect-local', async (_event, name) => {
      if (typeof name !== 'string' || !name) return null
      try {
        const response = await fetch(`${gateway()}/providers/${name}/connect`, {
          method: 'POST',
          // Long enough for a local server that is starting up, short enough
          // that a wrong port does not hang the button.
          signal: AbortSignal.timeout(20_000)
        })
        if (!response.ok) return { connected: false, models: 0, detail: 'the Gateway refused' }
        const body = (await response.json()) as Record<string, never>
        return {
          connected: Boolean(body.connected),
          models: Number(body.models ?? 0),
          detail: String(body.detail ?? '')
        }
      } catch {
        return { connected: false, models: 0, detail: 'could not reach the Gateway' }
      }
    })
    ipcMain.handle('marvi:get-models', async (_event, options) => {
      const provider = typeof options?.provider === 'string' ? options.provider : ''
      const refresh = options?.refresh === true
      const query = new URLSearchParams()
      if (provider) query.set('provider', provider)
      if (refresh) query.set('refresh', 'true')
      try {
        // Longer than the other calls on purpose: this one can reach several
        // providers' APIs, and a picker that gives up at five seconds is a
        // picker that looks empty on a slow network.
        const response = await fetch(`${gateway()}/models?${query}`, {
          signal: AbortSignal.timeout(20_000)
        })
        return response.ok ? normaliseModelPage(await response.json()) : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:get-upstreams', async (_event, model) => {
      const query = new URLSearchParams()
      if (typeof model === 'string' && model) query.set('model', model)
      try {
        const response = await fetch(`${gateway()}/providers/openrouter/upstreams?${query}`, {
          signal: AbortSignal.timeout(15_000)
        })
        return response.ok ? normaliseUpstreamPage(await response.json()) : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:set-provider-settings', async (_event, values) => {
      if (typeof values !== 'object' || values === null) return null
      try {
        const response = await fetch(`${gateway()}/providers/settings`, {
          method: 'PUT',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ values }),
          signal: AbortSignal.timeout(8_000)
        })
        return response.ok ? normaliseProviderPage(await response.json()) : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:get-memory-settings', async () => {
      try {
        const response = await fetch(`${gateway()}/memory/settings`, {
          signal: AbortSignal.timeout(5_000)
        })
        return response.ok ? normaliseMemory(await response.json()) : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:set-memory-settings', async (_event, update) => {
      if (!isRecord(update)) return null
      try {
        const response = await fetch(`${gateway()}/memory/settings`, {
          method: 'PUT',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(update),
          signal: AbortSignal.timeout(8_000)
        })
        return response.ok ? normaliseMemory(await response.json()) : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:get-skill-proposal', async () => {
      try {
        const response = await fetch(`${gateway()}/memory/proposal`, {
          signal: AbortSignal.timeout(5_000)
        })
        if (!response.ok) return null
        const body = await response.json()
        return isRecord(body) && isRecord(body.proposal) ? normaliseProposal(body.proposal) : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:settle-skill-proposal', async (_event, accept) => {
      try {
        const response = await fetch(`${gateway()}/memory/proposal`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ accept: accept === true }),
          signal: AbortSignal.timeout(8_000)
        })
        return response.ok
      } catch {
        return false
      }
    })
    ipcMain.handle('marvi:get-language', async () => {
      try {
        const response = await fetch(`${gateway()}/language`, {
          signal: AbortSignal.timeout(5_000)
        })
        return response.ok ? normaliseLanguage(await response.json()) : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:set-language', async (_event, update) => {
      if (!isRecord(update)) return null
      try {
        const response = await fetch(`${gateway()}/language`, {
          method: 'PUT',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(update),
          signal: AbortSignal.timeout(8_000)
        })
        return response.ok ? normaliseLanguage(await response.json()) : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:get-workspace', async () => {
      try {
        const response = await fetch(`${gateway()}/workspace`, {
          signal: AbortSignal.timeout(5_000)
        })
        return response.ok ? normaliseWorkspace(await response.json()) : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:set-workspace', async (_event, update) => {
      if (typeof update !== 'object' || update === null) return null
      try {
        const response = await fetch(`${gateway()}/workspace`, {
          method: 'PUT',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(update),
          signal: AbortSignal.timeout(8_000)
        })
        const body = await response.json().catch(() => null)
        // The body carries why on a refusal — a root that is not a folder, a
        // scope that is not a scope. A bare null here would read as "nothing
        // happened", which is the one thing it did not do.
        if (!response.ok) {
          const detail = isRecord(body) ? body.detail : null
          return { error: typeof detail === 'string' ? detail : 'the change was refused' }
        }
        return normaliseWorkspace(body)
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:answer-question', async (_event, update) => {
      // Only clears the card. The answer itself goes into the room as the
      // user's own turn, from the renderer, because that is what an answer is.
      if (!isRecord(update)) return false
      try {
        const response = await fetch(`${gateway()}/voice/question/answer`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            id: String(update.id ?? ''),
            answer: String(update.answer ?? '')
          }),
          signal: AbortSignal.timeout(5_000)
        })
        return response.ok
      } catch {
        return false
      }
    })
    ipcMain.handle('marvi:save-secret', async (_event, update) => {
      // The only path a credential takes: renderer -> here -> Gateway ->
      // settings store. It is never returned, never logged, and never sent
      // into the room the way a clarify answer is.
      if (!isRecord(update)) return false
      try {
        const response = await fetch(`${gateway()}/voice/secret`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            id: String(update.id ?? ''),
            name: String(update.name ?? ''),
            value: String(update.value ?? '')
          }),
          signal: AbortSignal.timeout(8_000)
        })
        return response.ok
      } catch {
        return false
      }
    })
    ipcMain.handle('marvi:choose-folder', async () => {
      // The native picker, rather than a text field. A workspace root typed by
      // hand is a workspace root with a typo in it, and the refusal that
      // follows names a path that looks correct.
      const chosen = await dialog.showOpenDialog({
        title: 'Choose a workspace folder',
        properties: ['openDirectory', 'createDirectory']
      })
      return chosen.canceled ? '' : (chosen.filePaths[0] ?? '')
    })
    ipcMain.handle('marvi:choose-memory-files', async () => {
      const chosen = await dialog.showOpenDialog({
        title: 'Choose memory files to import',
        // Markdown for a hand-written MEMORY.md, JSON for a Mem0 or Honcho
        // export. `All files` last, because an export can arrive named
        // anything and refusing to show it is worse than reading it and
        // finding nothing.
        filters: [
          { name: 'Memory files', extensions: ['md', 'json', 'jsonl', 'txt'] },
          { name: 'All files', extensions: ['*'] }
        ],
        properties: ['openFile', 'multiSelections']
      })
      return chosen.canceled ? [] : chosen.filePaths
    })
    ipcMain.handle('marvi:revise-memory', (_event, id, subject, body) =>
      gatewayJson(`/memory/${Number(id)}`, {
        method: 'PATCH',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ subject: String(subject ?? ''), body: String(body ?? '') })
      })
    )
    ipcMain.handle('marvi:delete-memory', (_event, id) =>
      gatewayJson(`/memory/${Number(id)}`, { method: 'DELETE' })
    )
    ipcMain.handle('marvi:edit-entity', (_event, name, renameTo, remove) =>
      gatewayJson('/arc/memory/graph/entity', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          name: String(name ?? ''),
          rename_to: String(renameTo ?? ''),
          remove: remove === true
        })
      })
    )
    ipcMain.handle('marvi:get-import-sources', async () => {
      const body = await gatewayJson('/memory/import/sources')
      if (!isRecord(body)) return null
      return {
        packPrompt: String(body.pack_prompt ?? ''),
        packFormat: String(body.pack_format ?? ''),
        provider: String(body.provider ?? 'local'),
        honcho: body.honcho === true,
        mem0: body.mem0 === true
      }
    })
    ipcMain.handle('marvi:get-honcho-workspaces', () =>
      // Reaching the Honcho API and listing an account's workspaces; slower
      // than a local read and not slow enough to need a spinner of its own.
      gatewayJson('/memory/import/honcho/workspaces', undefined, 30_000)
    )
    ipcMain.handle('marvi:preview-memory-import', (_event, request) =>
      gatewayJson(
        '/memory/import/preview',
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(isRecord(request) ? request : { paths: [] })
        },
        // A provider preview reads every peer in a workspace.
        120_000
      )
    )
    ipcMain.handle('marvi:import-memories', (_event, request) =>
      gatewayJson(
        '/memory/import',
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(isRecord(request) ? request : { paths: [] })
        },
        // A model call per twenty-five memories, then a dream over the result.
        // Five minutes is a large import, not a hung one.
        300_000
      )
    )
    ipcMain.handle('marvi:start-oauth', async (_event, name) => {
      if (typeof name !== 'string') return { ok: false, detail: 'no provider' }
      try {
        const response = await fetch(`${gateway()}/providers/${name}/oauth/start`, {
          method: 'POST',
          signal: AbortSignal.timeout(8_000)
        })
        const body = (await response.json()) as { url?: string; detail?: string }
        if (!response.ok || !body.url) {
          return { ok: false, detail: body.detail ?? 'could not start sign-in' }
        }
        // The provider's own login page, in the user's own browser. Marvi never
        // renders it and never sees what is typed into it.
        void shell.openExternal(body.url)
        return { ok: true, detail: '' }
      } catch {
        return { ok: false, detail: 'Marvi Gateway is unavailable' }
      }
    })
    ipcMain.handle('marvi:poll-oauth', async (_event, name) => {
      if (typeof name !== 'string') return null
      try {
        const response = await fetch(`${gateway()}/providers/${name}/oauth/status`, {
          signal: AbortSignal.timeout(5_000)
        })
        return response.ok ? await response.json() : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:disconnect-provider', async (_event, name) => {
      if (typeof name !== 'string') return null
      try {
        const response = await fetch(`${gateway()}/providers/${name}/disconnect`, {
          method: 'POST',
          signal: AbortSignal.timeout(8_000)
        })
        return response.ok ? normaliseProviderPage(await response.json()) : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:get-identity', async () => {
      try {
        const response = await fetch(`${gateway()}/identity`, {
          signal: AbortSignal.timeout(3_000)
        })
        return response.ok ? await response.json() : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:set-identity', async (_event, update) => {
      if (typeof update !== 'object' || update === null) return null
      try {
        const response = await fetch(`${gateway()}/identity`, {
          method: 'PUT',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(update),
          signal: AbortSignal.timeout(5_000)
        })
        return response.ok ? await response.json() : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:get-room-events', async () => {
      try {
        const response = await fetch(`${gateway()}/room/events?limit=40`, {
          signal: AbortSignal.timeout(1_500)
        })
        if (!response.ok) return []
        const body = (await response.json()) as { events?: unknown }
        return Array.isArray(body.events) ? body.events : []
      } catch {
        return []
      }
    })
    // The room's write tools, through the same `/tools/{name}` path Marvi
    // uses -- so the sleep rule, local-action policy and audit line all apply
    // to a button press exactly as they do to a spoken request. The
    // renderer names the tool; it cannot reach anything the Gateway has not
    // registered, and the allowlist here keeps it to the room.
    ipcMain.handle('marvi:get-auxiliary', async () => {
      try {
        const response = await fetch(`${gateway()}/auxiliary`, {
          signal: AbortSignal.timeout(5_000)
        })
        if (!response.ok) return null
        const body = await response.json()
        if (!isRecord(body)) return null
        // Passed through except for the one field whose name has two words in
        // it. Everything else in this shape is a single word and survives.
        const roles = Array.isArray(body.roles) ? body.roles : []
        return {
          ...body,
          roles: roles.filter(isRecord).map((role) => ({
            ...role,
            effort: typeof role.effort === 'string' ? role.effort : '',
            effortSetting: typeof role.effort_setting === 'string' ? role.effort_setting : ''
          }))
        }
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:get-room-health', async () => {
      try {
        const response = await fetch(`${gateway()}/tools/room_health`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ arguments: {} }),
          signal: AbortSignal.timeout(5_000)
        })
        if (!response.ok) return null
        const body = (await response.json()) as { result?: { health?: unknown } }
        return body.result?.health ?? null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:get-face-library', async () => {
      try {
        const response = await fetch(`${gateway()}/room/vision/faces`, {
          signal: AbortSignal.timeout(8_000)
        })
        return response.ok ? await response.json() : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:get-room-vision-preview', async () => {
      try {
        const response = await fetch(`${gateway()}/room/vision/preview`, {
          signal: AbortSignal.timeout(3_000)
        })
        return response.ok ? await response.json() : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:room-command', async (_event, tool, args) => {
      const allowed = [
        'room_set_light',
        'room_set_mode',
        'smart_room_cancel_sleep',
        'smart_room_vision_identity'
      ]
      if (typeof tool !== 'string' || !allowed.includes(tool)) {
        return { status: 'failed', error: `not a room control: ${String(tool)}` }
      }
      try {
        const response = await fetch(`${gateway()}/tools/${tool}`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ arguments: args ?? {} }),
          signal: AbortSignal.timeout(8_000)
        })
        return await response.json()
      } catch (cause) {
        return { status: 'failed', error: cause instanceof Error ? cause.message : 'unreachable' }
      }
    })
    ipcMain.handle('marvi:get-room-state', async () => {
      try {
        const response = await fetch(`${gateway()}/tools/room_state`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ arguments: {} }),
          signal: AbortSignal.timeout(3_000)
        })
        if (!response.ok) return null
        return await response.json()
      } catch {
        return null
      }
    })
    ipcMain.on('marvi:show-main', showMainWindow)
    ipcMain.on('marvi:window-minimize', (event) => {
      if (!mainWindow || event.sender !== mainWindow.webContents) return
      mainWindow.minimize()
    })
    ipcMain.on('marvi:window-toggle-maximize', (event) => {
      if (!mainWindow || event.sender !== mainWindow.webContents) return
      if (mainWindow.isMaximized()) mainWindow.unmaximize()
      else mainWindow.maximize()
      broadcastWindowState()
    })
    ipcMain.on('marvi:window-close', (event) => {
      if (!mainWindow || event.sender !== mainWindow.webContents) return
      // Close on the frameless shell means "hide to tray", matching the
      // always-on contract. Quit stays explicit via the tray menu.
      mainWindow.hide()
    })
    ipcMain.handle('marvi:restart-all', (event) => {
      if (!mainWindow || event.sender !== mainWindow.webContents) return false
      desktop.info('whole application restart requested')
      setTimeout(() => restartApplication(app), 50)
      return true
    })
    ipcMain.handle('marvi:shutdown-all', (event) => {
      if (!mainWindow || event.sender !== mainWindow.webContents) return false
      desktop.info('whole application shutdown requested')
      setTimeout(() => shutdownApplication(app), 50)
      return true
    })
    ipcMain.handle('marvi:get-window-state', () => windowStatePayload())
    ipcMain.handle('marvi:set-translucency', (_event, value) => {
      const candidate = Number(value)
      if (!Number.isFinite(candidate)) return translucencyIntensity
      translucencyIntensity = Math.min(100, Math.max(0, Math.round(candidate)))
      applyWindowTranslucency(mainWindow)
      return translucencyIntensity
    })
    ipcMain.on('marvi:preview-assistant-state', (event, state) => {
      if (!mainWindow || event.sender !== mainWindow.webContents) return
      previewAssistantState(state)
    })
    ipcMain.on('marvi:voice-state', (event, state) => {
      if (!mainWindow || event.sender !== mainWindow.webContents) return
      const normalized = normalizeRuntimeStatus({ ...runtimeStatus, assistant: state })
      if (normalized) publishRuntime(normalized)
    })
    ipcMain.on('marvi:island-size', (event, value) => {
      if (!islandWindow || event.sender !== islandWindow.webContents) return
      const size = normalizeIslandContentSize(value)
      if (size && islandWindow && !islandWindow.isDestroyed()) {
        sizeAndPositionIsland(islandWindow, size)
      }
    })
    ipcMain.on('marvi:island-interactive', (event, requestedMode) => {
      if (!islandWindow || islandWindow.isDestroyed() || event.sender !== islandWindow.webContents)
        return
      const mode = normalizeIslandInteractionMode(requestedMode)
      islandWindow.setFocusable(mode === 'interactive')
      islandWindow.setIgnoreMouseEvents(mode === 'passive', { forward: true })
    })

    tray = createTray()
    islandWindow = createIslandWindow()
    syncPetWindow()
    mainWindow = createMainWindow()
    startPetCursorPolling()
    const repositionPet = (): void => syncPetWindow()
    screen.on('display-added', repositionPet)
    screen.on('display-removed', repositionPet)
    screen.on('display-metrics-changed', repositionPet)
    startGatewayPolling()

    app.on('activate', showMainWindow)
  })
}

app.on('window-all-closed', () => {
  // The tray and Dynamic Island are the always-on product surface.
})

app.on('before-quit', () => {
  isQuitting = true
  if (gatewayPoll) clearInterval(gatewayPoll)
  gatewayPoll = null
  if (petCursorPoll) clearInterval(petCursorPoll)
  petCursorPoll = null
  if (petRestartTimer) clearTimeout(petRestartTimer)
  petRestartTimer = null
  petHost?.stop()
  petHost = null
  petBounds = null
  // Synchronous: Electron does not await anything here, and a promise would
  // be abandoned mid-kill.
  supervisor?.stopAllNow()
  supervisor = null
  tray?.destroy()
  tray = null
  islandWindow = null
})
