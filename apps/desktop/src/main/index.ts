import { execFile } from 'node:child_process'
import { promisify } from 'node:util'

import {
  app,
  BrowserWindow,
  clipboard,
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
import { killStrays } from './processes'
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
import type {
  AssistantState,
  ModelPage,
  ProviderPage,
  ProviderRow,
  UsagePage,
  RuntimeStatus,
  UpstreamPage,
  VoicePage,
  WakeStatus
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
    MARVI_HOME: stateDir(),
    MARVI_LOG_DIR: logsDir()
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
async function wakeAutostart(
  action: 'enable' | 'disable' | 'status',
  device = ''
): Promise<{ autostart: boolean; running: boolean }> {
  const fallback = { autostart: false, running: false }
  const uv = findUv()
  if (!repoRoot || !uv) return fallback
  const args = [
    'run',
    '--project',
    'services/agent',
    'python',
    '-m',
    'marvi_agent.wake_autostart',
    action
  ]
  if (action === 'enable') {
    args.push('--app', app.getPath('exe'))
    // Baked into the registered command line, so a changed microphone only
    // takes effect once the listener is re-registered and restarted -- which
    // is why `enable` stops whatever is already running before starting.
    if (device.trim()) args.push('--device', device.trim())
  }
  try {
    const { stdout } = await execFileAsync(uv, args, {
      cwd: repoRoot,
      windowsHide: true,
      // The registered command is baked at this moment and then run by the
      // login shell, which has its own PATH and almost certainly not `uv` on
      // it. Passing the resolved path through means the registration holds an
      // absolute one rather than a name that only resolves in here.
      env: { ...process.env, MARVI_UV_PATH: uv }
    })
    const parsed = JSON.parse(stdout || '{}') as Record<string, unknown>
    // `registered` is the command line; its presence is the answer.
    const autostart =
      action === 'disable' ? false : Boolean(parsed['registered'] || parsed['autostart'])
    return { autostart, running: autostart }
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
    islandWindowBounds(display.workArea, contentSize, 6, islandPlacement.alignment),
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
    return publishRuntime(offlineRuntimeFrom(app.getVersion(), runtimeStatus))
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
      if (channel !== 'release' && channel !== 'dev') {
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
      try {
        const response = await fetch(`${gateway()}/accounts`, {
          signal: AbortSignal.timeout(5_000)
        })
        if (!response.ok) return { available: false, detail: 'Gateway unavailable', accounts: [] }
        const body = (await response.json()) as {
          available?: boolean
          detail?: string
          accounts?: Array<Record<string, unknown>>
        }
        return {
          available: Boolean(body.available),
          detail: typeof body.detail === 'string' ? body.detail : '',
          accounts: (body.accounts ?? []).map((row) => ({
            toolkit: String(row.toolkit ?? ''),
            status: String(row.status ?? ''),
            connected: Boolean(row.connected),
            needsReconnect: Boolean(row.needs_reconnect)
          }))
        }
      } catch {
        return { available: false, detail: 'Gateway unavailable', accounts: [] }
      }
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
        return response.ok
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
        return response.ok ? await response.json() : null
      } catch {
        return null
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
            error: String((body.listener as Record<string, unknown>)?.['error'] ?? '')
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
      return wakeAutostart(
        enabled ? 'enable' : 'disable',
        typeof device === 'string' ? device : ''
      )
    })
    ipcMain.handle('marvi:get-voices', async (): Promise<VoicePage | null> => {
      try {
        const response = await fetch(`${gateway()}/voices`, {
          signal: AbortSignal.timeout(5_000)
        })
        if (!response.ok) return null
        const body = (await response.json()) as Record<string, never>
        const rows = Array.isArray(body.voices) ? (body.voices as Array<Record<string, never>>) : []
        return {
          setting: String(body.setting ?? ''),
          selected: String(body.selected ?? ''),
          missing: Boolean(body.missing),
          voices: rows.map((row) => ({
            id: String(row.id ?? ''),
            name: String(row.name ?? ''),
            language: String(row.language ?? ''),
            gender: String(row.gender ?? '')
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
    // uses -- so the sleep rule, the confirmation flow and the audit line all
    // apply to a button press exactly as they do to a spoken request. The
    // renderer names the tool; it cannot reach anything the Gateway has not
    // registered, and the allowlist here keeps it to the room.
    ipcMain.handle('marvi:get-auxiliary', async () => {
      try {
        const response = await fetch(`${gateway()}/auxiliary`, {
          signal: AbortSignal.timeout(5_000)
        })
        return response.ok ? await response.json() : null
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
    ipcMain.on('marvi:island-interactive', (event, interactive) => {
      if (!islandWindow || islandWindow.isDestroyed() || event.sender !== islandWindow.webContents)
        return
      const enabled = interactive === true
      islandWindow.setFocusable(enabled)
      islandWindow.setIgnoreMouseEvents(!enabled, { forward: true })
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
