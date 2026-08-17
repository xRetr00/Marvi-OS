import { appendFileSync, mkdirSync, renameSync, statSync, unlinkSync } from 'node:fs'
import { join } from 'node:path'

/**
 * The shell's own log files.
 *
 * The Gateway owns the logging engine, and everything Python routes through it.
 * The Electron shell cannot: **the moment its logs matter most is the moment the
 * Gateway is not running.** Posting them over HTTP would lose exactly the lines
 * that explain why nothing started.
 *
 * So this writes directly, into the same directory and the same line format, so
 * `desktop.log` interleaves with the rest by timestamp and `errors.log` still
 * collects everything at warning and above from every source.
 *
 * It is deliberately small and synchronous. A logger with its own worker and
 * flush semantics is one more thing that can fail during startup, which is the
 * only time this is load-bearing.
 */

const MAX_BYTES = 8 * 1024 * 1024
const BACKUPS = 3

export type Level = 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL'

// Same rule as the Python side: values are scrubbed, not field names, so a
// credential is caught wherever it appears.
const SECRET_NAME = /(KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)/i
const SECRET_PATTERNS = [
  /\bsk-[A-Za-z0-9_-]{16,}/g,
  /\bghp_[A-Za-z0-9]{20,}/g,
  /(?:^|\s)(?:bearer)\s+[A-Za-z0-9._-]{12,}/gi,
  /([?&](?:api_?key|access_token|token|key)=)[^&\s]+/gi
]
const MIN_SECRET_LENGTH = 8
const REDACTED = '[redacted]'

let directory: string | null = null
let secrets: string[] = []

export function configure(logDirectory: string): string {
  directory = logDirectory
  try {
    mkdirSync(directory, { recursive: true })
  } catch {
    // A logger that cannot create its directory must not stop the app.
  }
  refreshSecrets()
  return directory
}

export function refreshSecrets(): void {
  const found = new Set<string>()
  for (const [name, value] of Object.entries(process.env)) {
    if (!SECRET_NAME.test(name)) continue
    const cleaned = (value ?? '').trim()
    if (cleaned.length >= MIN_SECRET_LENGTH) found.add(cleaned)
  }
  // Longest first, so a token containing another as a prefix is not
  // half-scrubbed and left recognisable.
  secrets = [...found].sort((a, b) => b.length - a.length)
}

function scrub(text: string): string {
  let output = text
  for (const secret of secrets) {
    if (output.includes(secret)) output = output.split(secret).join(REDACTED)
  }
  for (const pattern of SECRET_PATTERNS) {
    output = output.replace(pattern, (_match, prefix?: string) =>
      prefix ? `${prefix}${REDACTED}` : REDACTED
    )
  }
  return output
}

function rotate(path: string): void {
  try {
    if (statSync(path).size < MAX_BYTES) return
  } catch {
    return // no file yet
  }
  try {
    unlinkSync(`${path}.${BACKUPS}`)
  } catch {
    // the oldest backup may not exist
  }
  for (let n = BACKUPS - 1; n >= 1; n--) {
    try {
      renameSync(`${path}.${n}`, `${path}.${n + 1}`)
    } catch {
      // gaps in the sequence are fine
    }
  }
  try {
    renameSync(path, `${path}.1`)
  } catch {
    // if the rename fails the file simply keeps growing; not worth crashing
  }
}

function writeTo(file: string, line: string): void {
  if (!directory) return
  const path = join(directory, file)
  rotate(path)
  try {
    appendFileSync(path, line, 'utf8')
  } catch {
    // Logging must never become the failure it was meant to explain.
  }
}

function timestamp(): string {
  const now = new Date()
  const pad = (n: number, width = 2): string => String(n).padStart(width, '0')
  return (
    `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ` +
    `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())},` +
    `${pad(now.getMilliseconds(), 3)}`
  )
}

export function log(
  subsystem: string,
  level: Level,
  message: string,
  extras?: Record<string, unknown>
): void {
  let line = `${timestamp()} ${level.padEnd(7)} [${subsystem}] desktop — ${scrub(message)}`
  if (extras && Object.keys(extras).length > 0) {
    const rendered = Object.entries(extras)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
      .join(' ')
    line += ` | ${scrub(rendered)}`
  }
  line += '\n'

  writeTo(`${subsystem}.log`, line)
  // The fan-in: errors.log answers "what went wrong" across every source.
  if (level === 'WARNING' || level === 'ERROR' || level === 'CRITICAL') {
    writeTo('errors.log', line)
  }
}

export const desktop = {
  debug: (message: string, extras?: Record<string, unknown>) =>
    log('desktop', 'DEBUG', message, extras),
  info: (message: string, extras?: Record<string, unknown>) =>
    log('desktop', 'INFO', message, extras),
  warn: (message: string, extras?: Record<string, unknown>) =>
    log('desktop', 'WARNING', message, extras),
  error: (message: string, extras?: Record<string, unknown>) =>
    log('desktop', 'ERROR', message, extras)
}

/**
 * Install catchers for what Node would otherwise print and forget.
 *
 * An unhandled rejection in the main process is a silent failure that leaves
 * the shell in a broken state with nothing written down.
 */
export function installCatchers(): void {
  process.on('uncaughtException', (error) => {
    desktop.error(`uncaught exception: ${error.stack ?? error.message}`)
  })
  process.on('unhandledRejection', (reason) => {
    desktop.error(`unhandled rejection: ${String(reason)}`)
  })
}
