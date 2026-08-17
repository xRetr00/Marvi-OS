import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * Where the local services live.
 *
 * Until now the Gateway port appeared twice in this file — once in the spawn
 * arguments and once in the fetch base URL — and the LiveKit version appeared
 * in three files. Two copies of a port is a bug waiting for someone to change
 * one of them, and that is exactly the kind of thing that ends with a shell
 * polling a port nothing is listening on.
 *
 * So: `config/runtime.json` is the source, and the environment overrides it.
 * Nothing below is read from a literal anywhere else.
 */

interface RuntimeManifest {
  gateway: { host: string; port: number }
  livekit: { version: string; host: string; port: number }
}

// Only used when the manifest is missing entirely — a packaged build with a
// broken install. Starting with wrong-but-known values beats crashing, and the
// Doctor reports it.
const FALLBACK: RuntimeManifest = {
  gateway: { host: '127.0.0.1', port: 8765 },
  livekit: { version: '1.13.5', host: '127.0.0.1', port: 7880 }
}

let cached: RuntimeManifest | null = null

export function manifest(repoRoot: string | null): RuntimeManifest {
  if (cached) return cached
  if (repoRoot) {
    const path = join(repoRoot, 'config', 'runtime.json')
    try {
      if (existsSync(path)) {
        const parsed = JSON.parse(readFileSync(path, 'utf8')) as Partial<RuntimeManifest>
        cached = {
          gateway: { ...FALLBACK.gateway, ...parsed.gateway },
          livekit: { ...FALLBACK.livekit, ...parsed.livekit }
        }
        return cached
      }
    } catch {
      // A malformed manifest must not stop the app from starting. Fall through.
    }
  }
  cached = FALLBACK
  return cached
}

export function gatewayUrl(repoRoot: string | null): string {
  const configured = process.env['MARVI_GATEWAY_URL']?.trim()
  if (configured) return configured.replace(/\/$/, '')
  const { host, port } = manifest(repoRoot).gateway
  return `http://${host}:${port}`
}

export function gatewayBind(repoRoot: string | null): { host: string; port: string } {
  // Derived from the same URL the shell will poll, so the two cannot disagree.
  const url = new URL(gatewayUrl(repoRoot))
  return { host: url.hostname, port: url.port || '8765' }
}

export function livekitServerPath(repoRoot: string | null): string {
  const configured = process.env['MARVI_LIVEKIT_SERVER']?.trim()
  if (configured) return configured
  const version = manifest(repoRoot).livekit.version
  return join(
    process.env['LOCALAPPDATA'] ?? '',
    'Marvi-OS',
    'runtime',
    'livekit',
    version,
    'livekit-server.exe'
  )
}

export function livekitBind(repoRoot: string | null): { host: string; port: number } {
  const { host, port } = manifest(repoRoot).livekit
  return { host, port }
}

export function logsDir(): string {
  const configured = process.env['MARVI_LOG_DIR']?.trim()
  if (configured) return configured
  return join(process.env['LOCALAPPDATA'] ?? '', 'Marvi OS', 'logs')
}
