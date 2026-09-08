/** Main-owned guest views. Only authenticated Gateway connections see CDP.
 * The upstream Playwright BrowserModel confines routing to this workspace's tabs.
 * No app webContents, renderer IPC, or app-wide debugging port is exposed.
 */
import { BrowserWindow, session, WebContentsView } from 'electron'
import type { DownloadItem, Rectangle } from 'electron'
import { createServer } from 'node:http'
import { randomBytes, randomUUID, timingSafeEqual } from 'node:crypto'
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { WebSocketServer, WebSocket } from 'ws'
import { BrowserModel, type CDPMessage } from './vendor/playwright/browserModel'

type Proxy = { server: string; username: string; password: string }
type Guest = { view: WebContentsView; target: string; context?: string }
type Workspace = {
  id: string; profile: string; model: BrowserModel; guests: Map<number, Guest>
  socket?: WebSocket; downloads: Map<string, DownloadItem>; directory: string
  proxy: Proxy; attached: boolean; private: boolean
  rawSessions: Map<string, Guest>
}

const identity = (value: unknown): value is string => typeof value === 'string' && /^(default|[a-f0-9]{32})$/.test(value)
const webURL = (value: string): boolean => {
  try { return ['https:', 'http:'].includes(new URL(value).protocol) } catch { return false }
}

export class BrowserHost {
  readonly token = randomBytes(32).toString('hex')
  endpoint = ''
  private workspaces = new Map<string, Workspace>()
  private server = createServer()
  private sockets = new WebSocketServer({ noServer: true, maxPayload: 16 * 1024 * 1024 })
  private placement: { id: string; target?: string; bounds: Rectangle } | null = null
  private parent: BrowserWindow | null = null

  constructor(private directory: string, private reveal: () => void = () => {}, private diagnostic: (method: string, error: unknown) => void = () => {}) {}

  async start(): Promise<void> {
    const authorized = (headers: Record<string, unknown>): boolean => {
      if (headers.origin || headers['sec-fetch-site']) return false
      const value = headers.authorization
      const expected = `Bearer ${this.token}`
      return typeof value === 'string' && value.length === expected.length &&
        timingSafeEqual(Buffer.from(value), Buffer.from(expected))
    }
    this.server.on('request', async (request, response) => {
      if (!authorized(request.headers)) { response.writeHead(403).end(); return }
      try {
        let raw = ''
        for await (const part of request) {
          raw += part
          if (raw.length > 16384) throw new Error('Request too large')
        }
        const body = raw ? JSON.parse(raw) : {}
        if (request.method === 'POST' && request.url === '/open') {
          if (!identity(body.id) || !identity(body.profile)) throw new Error('Invalid identity')
          if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(body.proxy?.server)) throw new Error('Invalid proxy')
          if (this.workspaces.has(body.id)) throw new Error('Session already exists')
          if ([...this.workspaces.values()].some(w => w.profile === body.profile)) throw new Error('Profile in use')
          const workspace = await this.open(body.id, body.profile, body.proxy)
          response.setHeader('Content-Type', 'application/json')
          response.end(JSON.stringify({ endpoint: `${this.endpoint.replace('http:', 'ws:')}/${workspace.id}`, downloads: workspace.directory }))
        } else if (request.method === 'POST' && request.url === '/close') {
          await this.closeWorkspace(body.id)
          response.end('{}')
        } else if (request.method === 'POST' && request.url === '/private') {
          const workspace = this.workspaces.get(body.id)
          if (!workspace || typeof body.active !== 'boolean') throw new Error('Invalid session')
          workspace.private = body.active
          if (body.active) for (const item of workspace.downloads.values()) item.cancel()
          response.end('{}')
        } else if (request.method === 'POST' && request.url === '/profile/delete') {
          if (!identity(body.profile) || body.profile === 'default' || [...this.workspaces.values()].some(w => w.profile === body.profile)) throw new Error('Profile in use')
          const storage = session.fromPath(join(this.directory, 'electron-profiles', body.profile))
          await storage.clearStorageData()
          await storage.clearCache()
          await storage.clearAuthCache()
          await storage.closeAllConnections()
          await storage.cookies.flushStore()
          response.end('{}')
        } else { response.writeHead(404).end() }
      } catch { response.writeHead(409).end('{"error":"Browser host request refused"}') }
    })
    this.server.on('upgrade', (request, socket, head) => {
      const workspace = this.workspaces.get((request.url ?? '').slice(1))
      if (!authorized(request.headers) || !workspace || workspace.socket) { socket.destroy(); return }
      this.sockets.handleUpgrade(request, socket, head, ws => {
        workspace.socket = ws
        workspace.model.connectOverCDP(message => this.emit(workspace, message))
        ws.on('error', () => {})
        ws.on('message', async raw => {
          let message: CDPMessage | undefined
          try {
            message = JSON.parse(raw.toString())
            if (!message || typeof message.id !== 'number' || typeof message.method !== 'string') throw new Error('Invalid packet')
            const result = await this.command(workspace, message)
            this.emit(workspace, { id: message.id, sessionId: message.sessionId, result })
          } catch (error) {
            this.diagnostic(message?.method ?? 'invalid', error)
            if (message) this.emit(workspace, { id: message.id, sessionId: message.sessionId, error: { message: 'Guest command failed' } })
          }
        })
        ws.once('close', () => { void this.closeWorkspace(workspace.id) })
      })
    })
    await new Promise<void>(resolve => this.server.listen(0, '127.0.0.1', resolve))
    const address = this.server.address()
    if (!address || typeof address === 'string') throw new Error('Browser host unavailable')
    this.endpoint = `http://127.0.0.1:${address.port}`
  }

  private emit(workspace: Workspace, message: CDPMessage): void {
    if (workspace.socket?.readyState === WebSocket.OPEN) workspace.socket.send(JSON.stringify(message))
  }

  private async open(id: string, profile: string, proxy: Proxy): Promise<Workspace> {
    const directory = join(this.directory, 'transfers', id)
    mkdirSync(directory, { recursive: true })
    const workspace: Workspace = {
      id, profile, proxy, directory, guests: new Map(), downloads: new Map(),
      attached: false, private: false, rawSessions: new Map(),
      model: new BrowserModel(async (method, args) => {
        if (method === 'chrome.tabs.create') {
          const guest = await this.createGuest(workspace)
          const url = args[0]?.url
          if (url && url !== 'about:blank') {
            if (!webURL(url)) throw new Error('Invalid URL')
            await guest.view.webContents.loadURL(url)
          }
          return { id: guest.view.webContents.id }
        }
        if (method === 'chrome.tabs.remove') {
          const guest = workspace.guests.get(args[0])
          if (!guest) throw new Error('Unknown tab')
          guest.view.webContents.close()
          return
        }
        const guest = workspace.guests.get(args[0]?.tabId)
        if (!guest) throw new Error('Unknown tab')
        const debug = guest.view.webContents.debugger
        if (method === 'chrome.debugger.attach') {
          if (!debug.isAttached()) debug.attach('1.3')
          return
        }
        if (method === 'chrome.debugger.sendCommand') {
          const result = await debug.sendCommand(args[1], args[2], args[0].sessionId)
          if (args[1] === 'Target.getTargetInfo') {
            guest.target = result.targetInfo.targetId
            guest.context = result.targetInfo.browserContextId
          }
          return result
        }
        throw new Error('Unsupported host command')
      })
    }
    this.workspaces.set(id, workspace)
    this.reveal()
    const storage = session.fromPath(join(this.directory, 'electron-profiles', profile))
    await storage.setProxy({ mode: 'fixed_servers', proxyRules: proxy.server, proxyBypassRules: '<-loopback>' })
    await storage.closeAllConnections()
    storage.setPermissionRequestHandler((_wc, _permission, callback) => callback(false))
    storage.setPermissionCheckHandler(() => false)
    storage.setDevicePermissionHandler(() => false)
    storage.webRequest.onBeforeRequest((details, callback) => {
      callback({ cancel: details.url !== 'about:blank' && !webURL(details.url) })
    })
    storage.on('will-download', (_event, item, contents) => {
      if (!workspace.guests.has(contents.id) || workspace.private || !workspace.socket) { item.cancel(); return }
      const guid = randomUUID()
      item.setSavePath(join(directory, guid))
      item.pause()
      workspace.downloads.set(guid, item)
      item.on('updated', () => { if (item.getReceivedBytes() > 100 * 1024 * 1024) item.cancel() })
      item.once('done', (_event, state) => {
        this.emit(workspace, { method: 'Browser.downloadProgress', params: { guid, state: state === 'completed' ? 'completed' : 'canceled', receivedBytes: item.getReceivedBytes(), totalBytes: item.getTotalBytes() } })
        workspace.downloads.delete(guid)
      })
      void contents.debugger.sendCommand('Page.getFrameTree').then(({ frameTree }) => {
        this.emit(workspace, { method: 'Browser.downloadWillBegin', params: { guid, frameId: frameTree.frame.id, url: item.getURL(), suggestedFilename: item.getFilename() } })
        if (workspace.private) item.cancel(); else item.resume()
      }).catch(() => item.cancel())
    })
    await this.createGuest(workspace)
    return workspace
  }

  private async createGuest(workspace: Workspace): Promise<Guest> {
    const view = new WebContentsView({ webPreferences: {
      session: session.fromPath(join(this.directory, 'electron-profiles', workspace.profile)),
      sandbox: true, contextIsolation: true, nodeIntegration: false,
      webSecurity: true, backgroundThrottling: false, navigateOnDragDrop: false,
      disableDialogs: false
    } })
    const contents = view.webContents
    contents.setWebRTCIPHandlingPolicy('disable_non_proxied_udp')
    const guest: Guest = { view, target: '' }
    workspace.guests.set(contents.id, guest)
    contents.on('login', (event, _details, auth, callback) => {
      event.preventDefault()
      if (auth.isProxy && auth.host === '127.0.0.1' && auth.port === Number(new URL(workspace.proxy.server).port)) callback(workspace.proxy.username, workspace.proxy.password)
      else callback()
    })
    contents.on('will-navigate', (event, url) => { if (!webURL(url)) event.preventDefault() })
    contents.setWindowOpenHandler(details => {
      if (!webURL(details.url) || workspace.private) return { action: 'deny' }
      return { action: 'allow', createWindow: () => {
        // Electron needs a synchronous return. Create about:blank first via the
        // same helper; registration happens before its first await.
        const before = new Set(workspace.guests.keys())
        void this.createGuest(workspace)
        return [...workspace.guests.entries()].find(([id]) => !before.has(id))![1].view.webContents
      } }
    })
    contents.debugger.on('message', (_event, method, params, sessionId) => {
      if (['Runtime.consoleAPICalled', 'Runtime.exceptionThrown', 'Log.entryAdded'].includes(method)) return
      // Explicit user CDP sessions must not be auto-attached as new page
      // sessions by Playwright; that would replace its callback registry.
      if (method === 'Target.attachedToTarget' && params.targetInfo?.targetId === guest.target) {
        workspace.rawSessions.set(params.sessionId, guest)
        return
      }
      if (method === 'Target.detachedFromTarget' && workspace.rawSessions.has(params.sessionId)) {
        workspace.rawSessions.delete(params.sessionId)
        this.emit(workspace, { sessionId: workspace.id, method, params })
        return
      }
      workspace.model.onDebuggerEvent({ tabId: contents.id, sessionId: sessionId || undefined }, method, params)
    })
    contents.debugger.on('detach', () => workspace.model.onDebuggerDetach({ tabId: contents.id }))
    contents.once('destroyed', () => {
      workspace.guests.delete(contents.id)
      workspace.model.onTabRemoved(contents.id)
      this.layout()
    })
    workspace.model.onTabCreated({ id: contents.id })
    this.layout()
    await contents.loadURL('about:blank')
    return guest
  }

  private async command(workspace: Workspace, message: CDPMessage): Promise<unknown> {
    const { method, params = {} } = message
    const sessionId = message.sessionId === workspace.id ? undefined : message.sessionId
    if (workspace.private && /^(Input\.|DOM\.|Runtime\.(evaluate|callFunctionOn)|Page\.capture)/.test(method!)) throw new Error('Private input is active')
    if (method === 'Target.attachToBrowserTarget') return { sessionId: workspace.id }
    if (sessionId && workspace.rawSessions.has(sessionId)) {
      return workspace.rawSessions.get(sessionId)!.view.webContents.debugger.sendCommand(method!, params, sessionId)
    }
    if (method === 'Browser.getVersion') return { protocolVersion: '1.3', product: `Chrome/${process.versions.chrome}`, userAgent: session.defaultSession.getUserAgent() }
    if (method === 'Browser.setDownloadBehavior') return {} // Native DownloadItem stages files with CDP GUIDs.
    if (method === 'Browser.cancelDownload') { workspace.downloads.get(params.guid)?.cancel(); return {} }
    if (method === 'Target.setAutoAttach' && !sessionId) {
      await workspace.model.enableAutoAttach(); workspace.attached = true; return {}
    }
    if (method === 'Target.createTarget') return workspace.model.createTarget(params.url)
    if (method === 'Target.closeTarget') return workspace.model.closeTarget(params.targetId)
    if (method === 'Target.getTargetInfo') return { targetInfo: workspace.model.getTargetInfo(sessionId) ?? { targetId: workspace.id, type: 'browser', attached: true } }
    if (method === 'Target.attachToTarget' && !sessionId) {
      const guest = [...workspace.guests.values()].find(g => g.target === params.targetId)
      if (!guest) throw new Error('Unknown tab')
      const result = await guest.view.webContents.debugger.sendCommand(method, params)
      workspace.rawSessions.set(result.sessionId, guest)
      return result
    }
    if (method === 'Target.detachFromTarget' && !sessionId) {
      if (params.sessionId === workspace.id) return {}
      const guest = workspace.rawSessions.get(params.sessionId)
      if (!guest) throw new Error('Unknown session')
      return guest.view.webContents.debugger.sendCommand(method, params)
    }
    // Never forward browser-wide Target commands into Electron's real browser.
    if (method?.startsWith('Target.') && !['Target.setAutoAttach', 'Target.detachFromTarget'].includes(method)) throw new Error('Unsupported target command')
    if (method === 'Browser.getWindowForTarget') return { windowId: 1, bounds: { left: 0, top: 0, width: 1000, height: 700, windowState: 'normal' } }
    if (method === 'Browser.setWindowBounds') return {}
    if (method === 'Page.bringToFront') { this.reveal(); return {} }
    if (method === 'Browser.close') { setImmediate(() => { void this.closeWorkspace(workspace.id) }); return {} }
    if (!sessionId) {
      if (!['Storage.getCookies', 'Storage.setCookies', 'Storage.clearCookies'].includes(method!)) throw new Error('Unsupported browser command')
      const guest = [...workspace.guests.values()][0]
      if (!guest?.context) throw new Error('Missing browser context')
      params.browserContextId = guest.context
    }
    return sessionId ? workspace.model.sendCommand(sessionId, method!, params) : workspace.model.sendBrowserCommand(method!, params)
  }

  /** Only the trusted control renderer can request placement; it never sees CDP. */
  place(parent: BrowserWindow, value: { id: string; target?: string; bounds: Rectangle } | null): void {
    if (value) {
      const { x, y, width, height } = value.bounds
      const size = parent.getContentBounds()
      if (![x, y, width, height].every(Number.isFinite) || x < 0 || y < 40 || width < 1 || height < 1 || x + width > size.width + 1 || y + height > size.height + 1) throw new Error('Invalid browser placement')
      value = { ...value, bounds: { x: Math.round(x), y: Math.round(y), width: Math.round(width), height: Math.round(height) } }
    }
    this.parent = parent
    this.placement = value
    this.layout()
  }

  private layout(): void {
    const parent = this.parent
    if (!parent || parent.isDestroyed()) return
    for (const workspace of this.workspaces.values()) {
      const selected = [...workspace.guests.values()].find(g => g.target === this.placement?.target) ?? [...workspace.guests.values()][0]
      for (const guest of workspace.guests.values()) {
        const show = workspace.id === this.placement?.id && guest === selected
        if (!parent.contentView.children.includes(guest.view)) parent.contentView.addChildView(guest.view)
        guest.view.setVisible(show)
        if (show && this.placement) guest.view.setBounds(this.placement.bounds)
      }
    }
  }

  async closeWorkspace(id: string): Promise<void> {
    const workspace = this.workspaces.get(id)
    if (!workspace) return
    this.workspaces.delete(id)
    for (const item of workspace.downloads.values()) item.cancel()
    for (const { view } of workspace.guests.values()) {
      if (this.parent && !this.parent.isDestroyed()) this.parent.contentView.removeChildView(view)
      if (!view.webContents.isDestroyed()) view.webContents.close()
    }
    workspace.socket?.close()
    const storage = session.fromPath(join(this.directory, 'electron-profiles', workspace.profile))
    storage.removeAllListeners('will-download')
    storage.flushStorageData()
    await storage.cookies.flushStore()
  }

  async close(): Promise<void> {
    for (const id of [...this.workspaces.keys()]) await this.closeWorkspace(id)
    this.sockets.close()
    this.server.close()
  }
}
