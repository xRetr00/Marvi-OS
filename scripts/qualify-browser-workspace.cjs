// Real Electron host + Python Gateway browser service protocol qualification.
const { app, BrowserWindow } = require('electron')
const { spawn } = require('node:child_process')
const { resolve } = require('node:path')
const { BrowserHost } = require('../output/browser-host.cjs')
app.commandLine.appendSwitch('disable-features', 'CalculateNativeWinOcclusion')
app.commandLine.appendSwitch('disable-quic')
let host, window, child
app.whenReady().then(async () => {
  window = new BrowserWindow({ width: 1100, height: 800, show: true, webPreferences: { sandbox: true } })
  await window.loadURL('data:text/html,<title>Marvi Browser Qualification</title><h3>Marvi embedded browser qualification</h3>')
  host = new BrowserHost(resolve('output/embedded-workspace/browser'), () => {}, (method, error) => console.error('PROTOCOL', method, String(error)))
  await host.start()
  if (process.env.MARVI_PROTOCOL_TRACE) {
    const emit = host.emit.bind(host), command = host.command.bind(host)
    host.emit = (w, m) => { console.log('OUT', m.id, m.sessionId, m.method, m.method?.startsWith('Target.') ? JSON.stringify(m.params) : ''); emit(w, m) }
    host.command = (w, m) => { console.log('IN', m.id, m.sessionId, m.method); return command(w, m) }
  }
  child = spawn(resolve('.venv/Scripts/python.exe'), [resolve('scripts/qualify-browser-workspace.py')], {
    env: { ...process.env, MARVI_TEST_HOST: host.endpoint, MARVI_TEST_TOKEN: host.token },
    stdio: ['pipe', 'pipe', 'inherit'], windowsHide: true
  })
  let lines = ''
  child.stdout.on('data', chunk => {
    lines += chunk
    for (;;) {
      const index = lines.indexOf('\n')
      if (index < 0) break
      const line = lines.slice(0, index); lines = lines.slice(index + 1)
      if (line.startsWith('SESSION ')) host.place(window, { id: line.slice(8).trim(), bounds: { x: 10, y: 70, width: 1050, height: 630 } })
      else console.log(line)
    }
  })
  child.on('exit', async code => { await host.close(); window.destroy(); app.exit(code || 0) })
}).catch(error => { console.error(error); app.exit(1) })
