import { app, BrowserWindow, ipcMain, Menu, nativeImage, screen, shell, Tray } from 'electron'
import { is } from '@electron-toolkit/utils'
import { type ChildProcess, spawn } from 'child_process'
import { existsSync } from 'fs'
import { join, resolve } from 'path'
import icon from '../../resources/icon.png?asset'
import trayIcon from '../../resources/tray-icon.png?asset'
import { offlineRuntime, normalizeRuntimeStatus } from './gateway-runtime'
import {
  islandWindowBounds,
  normalizeIslandContentSize,
  type IslandContentSize,
  type IslandPlacement
} from './island-window'
import {
  canUpdate,
  consumeUpdateResult,
  startUpdate,
  updateInProgress,
  updateStateDir
} from './updater'
import type { AssistantState, RuntimeStatus } from '../shared/runtime'

let mainWindow: BrowserWindow | null = null
let islandWindow: BrowserWindow | null = null
let tray: Tray | null = null
let gatewayPoll: NodeJS.Timeout | null = null
let voiceProcesses: ChildProcess[] = []
let runtimeStatus: RuntimeStatus = offlineRuntime('unknown')
let islandPlacement: IslandPlacement = { displayId: null, alignment: 'center' }
let islandContentSize: IslandContentSize = { width: 76, height: 8 }
let isQuitting = false
let translucencyIntensity = 0
const GATEWAY_BASE_URL = 'http://127.0.0.1:8765'

// The renderer owns the translucency lever (0–100) and mirrors it here; the
// main process maps it to native window opacity. Floor the most see-through
// setting at 0.3 so it stays usable. 0 = fully opaque.
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

function startDevelopmentVoiceStack(): void {
  if (!is.dev || process.env['MARVI_MANAGE_VOICE_STACK'] === '0') return
  const repoRoot = resolve(app.getAppPath(), '../..')
  const livekit = join(
    process.env['LOCALAPPDATA'] ?? '',
    'Marvi-OS/runtime/livekit/1.13.5/livekit-server.exe'
  )
  const common = { cwd: repoRoot, windowsHide: true, stdio: 'ignore' as const }
  if (existsSync(livekit)) {
    voiceProcesses.push(spawn(livekit, ['--dev', '--bind', '127.0.0.1'], common))
  }
  voiceProcesses.push(
    spawn(
      'uv',
      [
        'run',
        '--project',
        'services/gateway',
        'uvicorn',
        'marvi_gateway.app:app',
        '--host',
        '127.0.0.1',
        '--port',
        '8765'
      ],
      common
    )
  )
  voiceProcesses.push(
    spawn(
      'uv',
      ['run', '--project', 'services/agent', 'python', '-m', 'marvi_agent.session', 'dev'],
      common
    )
  )
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
    // region, window controls), adapted from the Marvi/Hermes desktop
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
  const response = await fetch(`${GATEWAY_BASE_URL}${path}`, {
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

app.whenReady().then(() => {
  app.setAppUserModelId('ai.neuretro.marvi-os')
  startDevelopmentVoiceStack()

  ipcMain.handle('marvi:get-version', () => app.getVersion())
  ipcMain.handle('marvi:get-build-info', () => ({
    version: app.getVersion(),
    commit: process.env['MARVI_BUILD_COMMIT'] ?? 'development',
    buildTime: process.env['MARVI_BUILD_TIME'] ?? 'development',
    platform: process.platform,
    arch: process.arch,
    updateChannel: process.env['MARVI_UPDATE_CHANNEL'] ?? 'local'
  }))
  ipcMain.handle('marvi:get-runtime', () => runtimeStatus)
  ipcMain.handle('marvi:get-voice-session', async () => {
    const response = await fetch(`${GATEWAY_BASE_URL}/livekit/session`, {
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
      const response = await fetch(
        `${GATEWAY_BASE_URL}/confirmations/${encodeURIComponent(token)}`,
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ decision, arguments: pending.arguments }),
          signal: AbortSignal.timeout(10_000)
        }
      )
      const body = (await response.json()) as { runtime?: unknown }
      const normalized = normalizeRuntimeStatus(body.runtime)
      return normalized ? publishRuntime(normalized) : await refreshGatewayRuntime()
    } catch {
      return runtimeStatus
    }
  })
  ipcMain.handle('marvi:get-audit', async () => {
    try {
      const response = await fetch(`${GATEWAY_BASE_URL}/audit?limit=100`, {
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
    const root = resolve(app.getAppPath(), '../..')
    return {
      supported: canUpdate(root),
      inProgress: updateInProgress(updateStateDir(process.env['LOCALAPPDATA'])),
      branch: process.env['MARVI_UPDATE_BRANCH'] ?? 'main',
      root
    }
  })
  ipcMain.handle('marvi:consume-update-result', () =>
    consumeUpdateResult(updateStateDir(process.env['LOCALAPPDATA']))
  )
  ipcMain.handle('marvi:start-update', () => {
    const root = resolve(app.getAppPath(), '../..')
    const started = startUpdate({
      installRoot: root,
      branch: process.env['MARVI_UPDATE_BRANCH'] ?? 'main',
      desktopPid: process.pid,
      relaunchExe: process.execPath
    })
    if (started) {
      // The updater waits for this process to exit before touching the
      // checkout, so quitting is part of the handoff, not a side effect.
      isQuitting = true
      setTimeout(() => app.quit(), 250)
    }
    return started
  })
  ipcMain.handle('marvi:get-initiative', async () => {
    try {
      const response = await fetch(`${GATEWAY_BASE_URL}/initiative`, {
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
      const response = await fetch(`${GATEWAY_BASE_URL}/initiative`, {
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
      const response = await fetch(`${GATEWAY_BASE_URL}/mind/decisions?limit=60`, {
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
      const response = await fetch(`${GATEWAY_BASE_URL}/memory?limit=60`, {
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
      const response = await fetch(`${GATEWAY_BASE_URL}/memory`, {
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
      const response = await fetch(`${GATEWAY_BASE_URL}/accounts`, {
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
  ipcMain.handle('marvi:get-room-events', async () => {
    try {
      const response = await fetch(`${GATEWAY_BASE_URL}/room/events?limit=40`, {
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
      const response = await fetch(`${GATEWAY_BASE_URL}/tools/room_state`, {
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

app.on('window-all-closed', () => {
  // The tray and Dynamic Island are the always-on product surface.
})

app.on('before-quit', () => {
  isQuitting = true
  if (gatewayPoll) clearInterval(gatewayPoll)
  gatewayPoll = null
  for (const process of voiceProcesses) process.kill()
  voiceProcesses = []
  tray?.destroy()
  tray = null
  islandWindow = null
})
