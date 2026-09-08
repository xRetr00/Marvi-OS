// Real Electron host + Python Gateway browser service protocol qualification.
const { app, BrowserWindow } = require('electron')
const { spawn } = require('node:child_process')
const { resolve } = require('node:path')
const { mkdtempSync, writeFileSync, readFileSync } = require('node:fs')
const { tmpdir } = require('node:os')
const assert = require('node:assert/strict')
const { BrowserHost } = require('../output/browser-host.cjs')
app.commandLine.appendSwitch('disable-features', 'CalculateNativeWinOcclusion')
app.commandLine.appendSwitch('disable-quic')
let host, window, child
const directory = mkdtempSync(resolve(tmpdir(), 'marvi-workspace-proof-'))
app.whenReady().then(async () => {
  window = new BrowserWindow({ width: 1100, height: 800, show: true, webPreferences: { sandbox: true } })
  await window.loadURL('data:text/html,<title>Marvi Browser Qualification</title><h3>Marvi embedded browser qualification</h3>')
  host = new BrowserHost(resolve(directory, 'browser'), () => {}, (method, error) => console.error('PROTOCOL', method, String(error)), async id => {
    assert.equal(host.workspaces.get(id).private, true, 'Gateway must acknowledge private input first')
  })
  await host.start()
  const cookies = resolve(directory, 'cookies.json')
  writeFileSync(cookies, JSON.stringify({ cookies: [{ domain: '127.0.0.1', hostOnly: true, name: 'marvi-fixture', value: 'imported-cookie', path: '/', expirationDate: Date.now()/1000+3600 }, { domain: 'example.com', name: 'partitioned', value: 'fixture', partitionKey: {} }] }))
  assert.deepEqual(await host.importProfile('default', 'cookies', cookies), { imported: 1, skipped: 1 })
  if (process.env.MARVI_PROTOCOL_TRACE) {
    const emit = host.emit.bind(host), command = host.command.bind(host)
    host.emit = (w, m) => { console.log('OUT', m.id, m.sessionId, m.method, m.method?.startsWith('Target.') ? JSON.stringify(m.params) : ''); emit(w, m) }
    host.command = (w, m) => { console.log('IN', m.id, m.sessionId, m.method); return command(w, m) }
  }
  child = spawn(resolve('.venv/Scripts/python.exe'), [resolve('scripts/qualify-browser-workspace.py')], {
    env: { ...process.env, MARVI_TEST_HOST: host.endpoint, MARVI_TEST_TOKEN: host.token, MARVI_TEST_DIRECTORY: directory },
    stdio: ['pipe', 'pipe', 'inherit'], windowsHide: true
  })
  let lines = ''
  child.stdout.on('data', chunk => {
    lines += chunk
    for (;;) {
      const index = lines.indexOf('\n')
      if (index < 0) break
      const line = lines.slice(0, index); lines = lines.slice(index + 1)
      if (line.startsWith('ORIGIN ')) {
        const file = resolve(directory, 'passwords.csv')
        writeFileSync(file, `name,url,username,password\nFixture,${line.slice(7).trim()},fixture-user,MARVI_PRIVATE_CANARY_9031\n`)
        void host.importProfile('default', 'passwords', file).then(result => {
          assert.equal(result.imported, 1)
          assert.equal(readFileSync(resolve(directory, 'browser/passwords/default.encrypted')).includes(Buffer.from('MARVI_PRIVATE_CANARY_9031')), false)
          child.stdin.write('imported\n')
        })
      } else if (line.startsWith('PRIVATE ')) {
        const id = line.slice(8).trim()
        const tab = [...host.workspaces.get(id).guests.keys()][0]
        void host.fillSavedLogin(id, tab, 'fixture-user').then(() => child.stdin.write('filled\n')).catch(error => { console.error(error); child.stdin.write('failed\n') })
      } else if (line.startsWith('SESSION ')) host.place(window, { id: line.slice(8).trim(), bounds: { x: 10, y: 70, width: 1050, height: 630 } })
      else console.log(line)
    }
  })
  child.on('exit', async code => { await host.close(); window.destroy(); app.exit(code || 0) })
}).catch(error => { console.error(error); app.exit(1) })
