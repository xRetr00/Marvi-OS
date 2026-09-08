// Run with node_modules/electron/dist/electron.exe scripts/qualify-embedded-browser.cjs
// Real Electron host proof only: no production bridge and no user accounts.
const { app, BrowserWindow, WebContentsView, session } = require('electron')
const assert = require('node:assert/strict')
const { createServer } = require('node:http')
const { mkdtemp, mkdir, writeFile } = require('node:fs/promises')
const { tmpdir } = require('node:os')
const { resolve, join } = require('node:path')

let window
let server
const views = new Set()
// Covered Windows windows still need a compositor surface for agent input/capture.
app.commandLine.appendSwitch('disable-features', 'CalculateNativeWinOcclusion')

async function main() {
  const directory = await mkdtemp(join(tmpdir(), 'marvi-embedded-proof-'))
  app.setPath('userData', join(directory, 'shell'))
  await app.whenReady()
  server = createServer((_request, response) => {
    response.setHeader('Content-Type', 'text/html; charset=utf-8')
    response.end('<h1>Marvi embedded browser fixture</h1><label>Test input <input id="field"></label><button onclick="document.querySelector(\'output\').textContent=document.querySelector(\'input\').value">Apply</button><output></output>')
  })
  await new Promise((done) => server.listen(0, '127.0.0.1', done))
  const url = `http://127.0.0.1:${server.address().port}/`
  window = new BrowserWindow({ width: 1000, height: 700, show: false,
    webPreferences: { sandbox: true, nodeIntegration: false, contextIsolation: true }
  })
  await window.loadURL('data:text/html,<body style="background:%230a0a0b;color:white;font:16px monospace">MARVI / BROWSER HOST PROOF</body>')

  async function guest(profile) {
    const storage = session.fromPath(join(directory, profile))
    storage.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))
    storage.setPermissionCheckHandler(() => false)
    const view = new WebContentsView({
      webPreferences: {
        session: storage, sandbox: true, nodeIntegration: false,
        contextIsolation: true, backgroundThrottling: false
      }
    })
    views.add(view)
    view.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
    window.contentView.addChildView(view)
    view.setBounds({ x: 20, y: 60, width: 940, height: 570 })
    view.setVisible(true)
    await view.webContents.loadURL(url)
    return view
  }

  window.show()
  const first = await guest('profile-a')
  first.webContents.focus()
  assert.equal(await first.webContents.executeJavaScript('typeof window.marvi'), 'undefined')
  assert.equal(await first.webContents.executeJavaScript('typeof require'), 'undefined')
  await first.webContents.executeJavaScript('localStorage.setItem("fixture", "profile-a"); document.querySelector("input").focus()')
  first.webContents.debugger.attach('1.3')
  await first.webContents.debugger.sendCommand('Input.insertText', { text: 'fixture input' })
  assert.equal(await first.webContents.executeJavaScript('document.querySelector("input").value'), 'fixture input')
  await new Promise(resolve => setTimeout(resolve, 300))
  const point = await first.webContents.executeJavaScript('(() => { const r=document.querySelector("button").getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2} })()')
  first.webContents.sendInputEvent({ type: 'mouseMove', x: Math.round(point.x), y: Math.round(point.y) })
  first.webContents.sendInputEvent({ type: 'mouseDown', button: 'left', clickCount: 1, x: Math.round(point.x), y: Math.round(point.y) })
  first.webContents.sendInputEvent({ type: 'mouseUp', button: 'left', clickCount: 1, x: Math.round(point.x), y: Math.round(point.y) })
  await first.webContents.executeJavaScript('new Promise(resolve => { let attempts=0; const timer=setInterval(() => { if(document.querySelector("output").textContent || ++attempts===100) {clearInterval(timer); resolve()} }, 20) })')
  const nativeClick = await first.webContents.executeJavaScript('document.querySelector("output").textContent') === 'fixture input'
  first.webContents.debugger.detach()
  const output = resolve('output/playwright/embedded-host-proof')
  await mkdir(output, { recursive: true })
  let capture = false
  try {
    const screenshot = await first.webContents.capturePage()
    capture = !screenshot.isEmpty()
    if (capture) await writeFile(join(output, 'guest.png'), screenshot.toPNG())
  } catch { /* Record the missing compositor surface rather than claiming visual proof. */ }
  window.contentView.removeChildView(first)
  first.webContents.close()
  views.delete(first)

  const restored = await guest('profile-a')
  assert.equal(await restored.webContents.executeJavaScript('localStorage.getItem("fixture")'), 'profile-a')
  const isolated = await guest('profile-b')
  assert.equal(await isolated.webContents.executeJavaScript('localStorage.getItem("fixture")'), null)
  // A hidden/detached control surface must not end the guest session.
  window.contentView.removeChildView(restored)
  assert.equal(restored.webContents.isDestroyed(), false)
  assert.equal(await restored.webContents.executeJavaScript('document.querySelector("h1").textContent'), 'Marvi embedded browser fixture')
  const evidence = {
    electron: process.versions.electron, chromium: process.versions.chrome,
    sandboxed_guest: true, no_shell_bridge: true, native_typing: true,
    native_click: nativeClick, guest_capture: capture,
    same_process_view_reopen_preserves_storage: true, separate_profiles: true,
    detached_guest_remains_alive: true,
    limitations: ['No application restart proof', 'No Gateway bridge', 'No private-input integration', 'Fixture only; no real-site authentication']
  }
  await writeFile(join(output, 'evidence.json'), JSON.stringify(evidence, null, 2))
  console.log(JSON.stringify(evidence))
  assert.ok(nativeClick && capture, 'Embedded native click/capture gate remains unqualified')
}

main().then(() => finish(0)).catch((error) => {
  console.error(error)
  finish(1)
})

function finish(code) {
  for (const view of views) {
    if (!view.webContents.isDestroyed()) view.webContents.close()
  }
  if (window && !window.isDestroyed()) window.destroy()
  if (server) server.close()
  app.exit(code)
}
