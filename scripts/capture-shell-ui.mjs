import { chromium } from 'playwright-core'
import { readFileSync } from 'fs'
import { resolve } from 'path'
import http from 'http'
import { createReadStream, statSync } from 'fs'

// Serve the built renderer over loopback so ES modules load (file:// is
// CORS-blocked for module scripts).
const root = resolve('apps/desktop/out/renderer')
const server = http.createServer((req, res) => {
  const path = decodeURIComponent((req.url ?? '/').split('?')[0])
  const file = resolve(root, `.${path === '/' ? '/index.html' : path}`)
  if (!file.startsWith(root)) {
    res.writeHead(403)
    res.end()
    return
  }
  try {
    statSync(file)
    const type = file.endsWith('.js')
      ? 'text/javascript'
      : file.endsWith('.css')
        ? 'text/css'
        : file.endsWith('.mp4')
          ? 'video/mp4'
          : file.endsWith('.webp')
            ? 'image/webp'
            : file.endsWith('.woff2')
              ? 'font/woff2'
              : 'text/html'
    res.writeHead(200, { 'content-type': type })
    createReadStream(file).pipe(res)
  } catch {
    res.writeHead(404)
    res.end()
  }
})
await new Promise((ok) => server.listen(8899, '127.0.0.1', ok))

const browser = await chromium.launch({
  executablePath: `${process.env.LOCALAPPDATA}\\ms-playwright\\chromium-1234\\chrome-win64\\chrome.exe`
})
const page = await browser.newPage({ viewport: { width: 1180, height: 760 } })
const mock = readFileSync('scripts/mock-bridge.js', 'utf8')
await page.addInitScript(mock)
page.on('pageerror', (e) => console.log('PAGE ERR:', e.message.slice(0, 300)))

await page.goto('http://127.0.0.1:8899/?surface=main', { waitUntil: 'load' })
await page.waitForTimeout(1400)
await page.screenshot({ path: resolve('output/evidence/shell-overview.png') })
console.log('overview ok, buttons:', await page.locator('button').count())

await page.click('button.nav-item:has-text("SETTINGS")')
await page.waitForTimeout(600)
await page.screenshot({ path: resolve('output/evidence/shell-settings.png') })
console.log('settings ok')

await page.click('button.nav-item:has-text("ABOUT")')
await page.waitForTimeout(600)
await page.screenshot({ path: resolve('output/evidence/shell-about.png') })
console.log('about ok')

await page.goto('http://127.0.0.1:8899/?surface=main&connecting=1', { waitUntil: 'load' })
await page.waitForTimeout(900)
await page.screenshot({ path: resolve('output/evidence/shell-connecting.png') })
console.log('connecting ok')

await browser.close()
server.close()
