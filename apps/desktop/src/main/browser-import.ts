/** Explicit user-selected exports only. Never decrypt or copy Chrome databases. */
import { parse } from 'csv-parse/sync'
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { dirname } from 'node:path'

export interface Login { origin: string; username: string; password: string }
export interface Encryption {
  isEncryptionAvailable(): boolean
  encryptString(value: string): Buffer
  decryptString(value: Buffer): string
}

export function passwordExport(text: string): Login[] {
  if (Buffer.byteLength(text) > 10 * 1024 * 1024) throw new Error('Export exceeds 10 MB')
  const rows = parse(text, { columns: true, bom: true, skip_empty_lines: true, max_record_size: 65536 }) as Record<string, string>[]
  if (rows.length > 10000) throw new Error('Export exceeds 10,000 entries')
  return rows.map(row => {
    let url: URL
    try { url = new URL(row.url) } catch { throw new Error('Password export contains an invalid website') }
    if (!['http:', 'https:'].includes(url.protocol) || typeof row.username !== 'string' || !row.password) throw new Error('Expected Chrome password CSV: url, username, password')
    return { origin: url.origin, username: row.username, password: row.password }
  })
}

export class BrowserPasswords {
  constructor(private file: string, private encryption: Encryption) {}
  private read(): Login[] {
    if (!this.encryption.isEncryptionAvailable()) throw new Error('Windows password protection is unavailable')
    if (!existsSync(this.file)) return []
    return JSON.parse(this.encryption.decryptString(readFileSync(this.file))) as Login[]
  }
  import(text: string): number {
    const entries = passwordExport(text)
    const merged = new Map(this.read().map(item => [item.origin + '\0' + item.username, item]))
    for (const item of entries) merged.set(item.origin + '\0' + item.username, item)
    const encrypted = this.encryption.encryptString(JSON.stringify([...merged.values()]))
    mkdirSync(dirname(this.file), { recursive: true })
    writeFileSync(this.file + '.tmp', encrypted)
    renameSync(this.file + '.tmp', this.file)
    return entries.length
  }
  forOrigin(origin: string): Login[] { return this.read().filter(item => item.origin === origin) }
}

/** Runs only in an isolated guest world after a user action and private-input ack. */
export function fillLogin(login: Login): void {
  if (location.origin !== login.origin) throw new Error('Website changed')
  const visible = (input: HTMLInputElement): boolean => !input.disabled && input.getClientRects().length > 0
  const passwords = [...document.querySelectorAll<HTMLInputElement>('input[type="password"]')].filter(visible)
  if (passwords.length !== 1) throw new Error('Choose a page with one visible password field')
  const password = passwords[0]
  if (password.form?.action && new URL(password.form.action).origin !== login.origin) throw new Error('Login form has a different destination')
  const container = password.form ?? document
  const usernames = [...container.querySelectorAll<HTMLInputElement>('input[autocomplete="username"], input[type="email"], input[type="text"], input:not([type])')].filter(visible)
  if (usernames.length > 1) throw new Error('Username field is ambiguous')
  const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  for (const [input, value] of [[usernames[0], login.username], [password, login.password]] as const) {
    if (!input) continue
    set.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
  }
}
