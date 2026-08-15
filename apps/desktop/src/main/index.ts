import { app, BrowserWindow, ipcMain, Menu, nativeImage, screen, shell, Tray } from 'electron'
import { is } from '@electron-toolkit/utils'
import { join } from 'path'
import icon from '../../resources/icon.png?asset'

let mainWindow: BrowserWindow | null = null
let islandWindow: BrowserWindow | null = null
let tray: Tray | null = null

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
    backgroundColor: '#050607',
    title: 'Marvi OS',
    icon,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      sandbox: true
    }
  })

  window.once('ready-to-show', () => window.show())
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

function positionIsland(window: BrowserWindow): void {
  const cursorDisplay = screen.getDisplayNearestPoint(screen.getCursorScreenPoint())
  const [width] = window.getSize()
  const x = Math.round(cursorDisplay.workArea.x + (cursorDisplay.workArea.width - width) / 2)
  const y = cursorDisplay.workArea.y + 10
  window.setPosition(x, y, false)
}

function createIslandWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 356,
    height: 78,
    show: false,
    frame: false,
    transparent: true,
    resizable: false,
    movable: true,
    skipTaskbar: true,
    alwaysOnTop: true,
    focusable: true,
    hasShadow: false,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      sandbox: true
    }
  })

  window.setAlwaysOnTop(true, 'screen-saver')
  window.setVisibleOnAllWorkspaces(true)
  window.once('ready-to-show', () => {
    positionIsland(window)
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

function createTray(): Tray {
  const instance = new Tray(nativeImage.createFromPath(icon))
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

  ipcMain.handle('marvi:get-version', () => app.getVersion())
  ipcMain.on('marvi:show-main', showMainWindow)

  tray = createTray()
  islandWindow = createIslandWindow()
  mainWindow = createMainWindow()

  app.on('activate', showMainWindow)
})

app.on('window-all-closed', () => {
  // The tray and Dynamic Island are the always-on product surface.
})

app.on('before-quit', () => {
  tray?.destroy()
  tray = null
  islandWindow = null
})
