import { execFile, type ChildProcess } from 'node:child_process'
import { resolve, join } from 'node:path'
import type { App } from 'electron'
import type { LocationState } from '../shared/location'

type Gateway = (path: string, init?: RequestInit, timeoutMs?: number) => Promise<unknown>

export function validFix(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false
  const fix = value as Record<string, unknown>
  if (!['ready', 'denied', 'unavailable', 'timeout', 'error'].includes(String(fix.status))) return false
  if (fix.status !== 'ready') return true
  return ['latitude', 'longitude', 'accuracy_m', 'timestamp'].every(
    (key) => typeof fix[key] === 'number' && Number.isFinite(fix[key])
  ) && Math.abs(fix.latitude as number) <= 90 && Math.abs(fix.longitude as number) <= 180
    && (fix.accuracy_m as number) >= 0
}

export class LocationHost {
  private child: ChildProcess | null = null
  private pending: Promise<unknown> | null = null
  private timer: ReturnType<typeof setInterval> | null = null
  private stopped = false
  constructor(private app: Pick<App, 'isPackaged' | 'getAppPath'>, private gateway: Gateway) {}

  start(): void {
    this.stopped = false
    void this.refresh(false)
    this.timer = setInterval(() => void this.refresh(false), 5 * 60_000)
  }

  stop(): void {
    this.stopped = true
    if (this.timer) clearInterval(this.timer)
    this.timer = null
    this.child?.kill()
  }

  async refresh(request: boolean): Promise<unknown> {
    if (this.pending) return this.pending
    this.pending = this.read(request).finally(() => { this.pending = null })
    return this.pending
  }

  private async read(request: boolean): Promise<unknown> {
    const state = await this.gateway('/location') as LocationState | null
    if (this.stopped || !state || state.settings.mode !== 'automatic') return state
    const executable = this.app.isPackaged
      ? join(process.resourcesPath, 'location-host', 'marvi-location-host.exe')
      : resolve(this.app.getAppPath(), '../location-host/target/release/marvi-location-host.exe')
    const fix = await new Promise<Record<string, unknown>>((resolveResult) => {
      this.child = execFile(executable, [request ? '--request' : '--read'],
        { windowsHide: true, timeout: request ? 90_000 : 25_000, maxBuffer: 16_384 }, (error, stdout) => {
          this.child = null
          if (error) return resolveResult({ status: error.killed ? 'timeout' : 'unavailable' })
          try {
            const value: unknown = JSON.parse(stdout)
            resolveResult(validFix(value) ? value as Record<string, unknown> : { status: 'error' })
          } catch { resolveResult({ status: 'error' }) }
        })
    })
    if (this.stopped) return null
    return this.gateway('/location/fix', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...fix, generation: state.generation,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone })
    })
  }
}
