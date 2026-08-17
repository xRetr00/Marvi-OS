import { app, BrowserWindow, ipcMain, Menu, nativeImage, screen, shell, Tray } from 'electron'
import { is } from '@electron-toolkit/utils'
import { existsSync } from 'fs'
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
import { offlineRuntime, normalizeRuntimeStatus } from './gateway-runtime'
import { type ServiceReport, ServiceSupervisor, findUv } from './services'
import {
  islandWindowBounds,
  normalizeIslandContentSize,
  type IslandContentSize,
  type IslandPlacement
} from './island-window'
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
import type { AssistantState, ProviderPage, ProviderRow, RuntimeStatus } from '../shared/runtime'

let mainWindow: BrowserWindow | null = null
let islandWindow: BrowserWindow | null = null
let tray: Tray | null = null
let gatewayPoll: NodeJS.Timeout | null = null
let supervisor: ServiceSupervisor | null = null
let serviceReports: ServiceReport[] = []
let repoRoot: string | null = null
let runtimeStatus: RuntimeStatus = offlineRuntime('unknown')
let islandPlacement: IslandPlacement = { displayId: null, alignment: 'center' }
let islandContentSize: IslandContentSize = { width: 76, height: 8 }
let isQuitting = false
let translucencyIntensity = 0

// The renderer owns the translucency lever (0–100) and mirrors it here; the
// main process maps it to native window opacity. Floor the most see-through
// setting at 0.3 so it stays usable. 0 = fully opaque.
/** The Gateway speaks snake_case; the renderer types are camelCase. */
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
          url: String((row.env as Record<string, string>)?.url ?? '')
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
    command: uv,
    args: ['run', '--project', 'services/agent', 'python', '-m', 'marvi_agent.session', 'dev'],
    cwd: repoRoot,
    env: childEnv
  })
  supervisor.startAll()
}

function rendererUrl(surface: 'main' | 'island'): string {
  return `${process.env['ELECTRON_RENDERER_URL']}?surface=${surface}`
}

function loadSurface(window: BrowserWindow, surface: 'main' | 'island'): void {
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
    // Frameless shell: the renderer paints its own title bar (brand, drag
    // region, window controls), adapted from the the predecessor assistant desktop
    // titleBarStyle:'hidden' pattern. The native frame never renders.
    frame: false,
    titleBarStyle: 'hidden',
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

function showMainWindow(): void {
  islandWindow?.showInactive()
  mainWindow ??= createMainWindow()
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.show()
  mainWindow.focus()
}

function publishRuntime(next: RuntimeStatus): RuntimeStatus {
  runtimeStatus = next
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('marvi:runtime-state', next)
  }
  if (islandWindow && !islandWindow.isDestroyed()) {
    islandWindow.webContents.send('marvi:runtime-state', next)
  }
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

async function refreshGatewayRuntime(): Promise<RuntimeStatus> {
  try {
    const gateway = await gatewayRequest('/runtime')
    return publishRuntime({
      ...gateway,
      assistant: {
        ...runtimeStatus.assistant,
        yolo: gateway.assistant.yolo,
        microphone: gateway.assistant.microphone,
        camera: gateway.assistant.camera,
        confirmation: gateway.assistant.confirmation ?? runtimeStatus.assistant.confirmation,
        roomEvent: gateway.assistant.roomEvent
      }
    })
  } catch {
    return publishRuntime(offlineRuntime(app.getVersion()))
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
  instance.setContextMenu(
    Menu.buildFromTemplate([
      { label: 'Open Marvi OS', click: showMainWindow },
      { type: 'separator' },
      { label: 'Quit', click: () => app.quit() }
    ])
  )
  instance.on('double-click', showMainWindow)
  return instance
}

// One Marvi, and only one.
//
// Two instances would each start a Gateway on 8765, an agent joining the same
// LiveKit room, and a vision loop on the same camera. The second of each fails
// in a way that looks like a bug rather than like a second copy, and both would
// write to the same databases. Electron's lock is the cheapest way to make that
// impossible; the second launch just surfaces the first.
if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
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
        return publishRuntime(offlineRuntime(app.getVersion()))
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
        return runtimeStatus
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
    ipcMain.handle('marvi:get-chat', async () => {
      try {
        const response = await fetch(`${gateway()}/chat`, { signal: AbortSignal.timeout(4_000) })
        return response.ok ? await response.json() : { messages: [], available: false }
      } catch {
        return { messages: [], available: false }
      }
    })
    ipcMain.handle('marvi:send-chat', async (_event, message) => {
      if (typeof message !== 'string') return null
      try {
        const response = await fetch(`${gateway()}/chat`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ message }),
          // A tool round trip can be slow; a short timeout would look like a bug.
          signal: AbortSignal.timeout(180_000)
        })
        return response.ok ? await response.json() : null
      } catch {
        return null
      }
    })
    ipcMain.handle('marvi:clear-chat', async () => {
      try {
        const response = await fetch(`${gateway()}/chat`, {
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
    mainWindow = createMainWindow()
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
  // Synchronous: Electron does not await anything here, and a promise would
  // be abandoned mid-kill.
  supervisor?.stopAllNow()
  supervisor = null
  tray?.destroy()
  tray = null
  islandWindow = null
})
