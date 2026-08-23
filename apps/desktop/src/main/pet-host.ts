import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'

import type { App } from 'electron'

import type { AssistantState } from '../shared/runtime'
import type { RectangleLike } from './pet-window'

export type PetHostCommand =
  | { type: 'state'; phase: AssistantState['phase'] }
  | { type: 'look'; direction: number | null }
  | ({ type: 'bounds' } & RectangleLike)
  | { type: 'exit' }

export interface PetHostPaths {
  executable: string
  atlas: string
}

export function encodePetHostCommand(command: PetHostCommand): string {
  return `${JSON.stringify(command)}\n`
}

export function resolvePetHostPaths(app: Pick<App, 'getAppPath' | 'isPackaged'>): PetHostPaths {
  if (app.isPackaged) {
    const root = join(process.resourcesPath, 'pet-host')
    return {
      executable: join(root, 'marvi-pet-host.exe'),
      atlas: join(root, 'spritesheet.webp')
    }
  }
  const desktopRoot = app.getAppPath()
  return {
    executable: resolve(desktopRoot, '..', 'pet-host', 'target', 'release', 'marvi-pet-host.exe'),
    atlas: resolve(
      desktopRoot,
      'src',
      'renderer',
      'src',
      'assets',
      'pet',
      'marvi',
      'spritesheet.webp'
    )
  }
}

export class NativePetHost {
  private child: ChildProcessWithoutNullStreams | null = null
  private readonly expectedExits = new WeakSet<ChildProcessWithoutNullStreams>()

  constructor(
    private readonly paths: PetHostPaths,
    private readonly onUnexpectedExit: (detail: {
      code: number | null
      signal: NodeJS.Signals | null
    }) => void,
    private readonly onDiagnostic: (level: 'info' | 'warning', message: string) => void
  ) {}

  get running(): boolean {
    return this.child !== null && this.child.exitCode === null
  }

  start(bounds: RectangleLike, phase: AssistantState['phase']): boolean {
    if (this.running) {
      this.send({ type: 'bounds', ...bounds })
      this.send({ type: 'state', phase })
      return true
    }
    if (!existsSync(this.paths.executable) || !existsSync(this.paths.atlas)) {
      this.onDiagnostic(
        'warning',
        `native pet host is unavailable (host=${this.paths.executable}, atlas=${this.paths.atlas})`
      )
      return false
    }

    const child = spawn(
      this.paths.executable,
      [
        '--atlas',
        this.paths.atlas,
        '--x',
        String(bounds.x),
        '--y',
        String(bounds.y),
        '--width',
        String(bounds.width),
        '--height',
        String(bounds.height)
      ],
      { windowsHide: true }
    )
    this.child = child
    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    child.stdin.on('error', (error) => {
      if (!this.expectedExits.has(child)) {
        this.onDiagnostic('warning', `native pet host input error: ${error.message}`)
      }
    })
    child.stdout.on('data', (chunk: string) => {
      if (chunk.includes('"ready"')) this.onDiagnostic('info', 'native pet host ready')
    })
    child.stderr.on('data', (chunk: string) => {
      this.onDiagnostic('warning', chunk.trim())
    })
    child.on('error', (error) =>
      this.onDiagnostic('warning', `native pet host error: ${error.message}`)
    )
    child.on('exit', (code, signal) => {
      if (this.child === child) this.child = null
      if (!this.expectedExits.has(child)) this.onUnexpectedExit({ code, signal })
    })
    this.send({ type: 'state', phase })
    return true
  }

  send(command: PetHostCommand): boolean {
    const child = this.child
    if (!child || child.exitCode !== null || child.stdin.destroyed) return false
    child.stdin.write(encodePetHostCommand(command))
    return true
  }

  stop(): void {
    const child = this.child
    if (!child) return
    this.expectedExits.add(child)
    this.send({ type: 'exit' })
    const timeout = setTimeout(() => {
      if (child.exitCode === null) child.kill()
    }, 1_000)
    timeout.unref()
    this.child = null
  }
}
