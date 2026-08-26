import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

import type { MessagingPreferences, MessagingStatus } from '../shared/runtime'
import { stateDir } from './config'

export const MESSAGING_SOURCE_COMMIT = '61977bb4d6b97ab2aece57d2405fa2f0b19e3ae0'

function preferencesPath(): string {
  return join(stateDir(), 'messaging.json')
}

export function messagingSourceRoot(repoRoot: string | null): string {
  return repoRoot ? join(repoRoot, 'vendor', 'marvi-agent') : ''
}

export function defaultMessagingHome(): string {
  const configured = process.env['MARVI_MESSAGING_HOME']?.trim()
  return configured || join(stateDir(), 'messaging-agent')
}

export function readMessagingPreferences(): MessagingPreferences {
  const fallback = { enabled: false, home: defaultMessagingHome() }
  try {
    const parsed = JSON.parse(readFileSync(preferencesPath(), 'utf8')) as Partial<MessagingPreferences>
    return {
      enabled: parsed.enabled === true,
      home: parsed.home?.trim() ? resolve(parsed.home) : fallback.home
    }
  } catch {
    return fallback
  }
}

export function writeMessagingPreferences(update: MessagingPreferences): MessagingPreferences {
  const next = {
    enabled: update.enabled === true,
    home: resolve(update.home?.trim() || defaultMessagingHome())
  }
  mkdirSync(stateDir(), { recursive: true })
  writeFileSync(preferencesPath(), `${JSON.stringify(next, null, 2)}\n`, { mode: 0o600 })
  return next
}

/** Read the platform enum from the pinned source instead of maintaining a list
 * that inevitably drifts from the messaging engine. */
export function messagingPlatforms(sourceRoot: string): string[] {
  try {
    const source = readFileSync(join(sourceRoot, 'gateway', 'config.py'), 'utf8')
    const block = /class Platform\(Enum\):([\s\S]*?)(?=\nclass\s|$)/.exec(source)?.[1] ?? ''
    const values = [...block.matchAll(/^\s+[A-Z][A-Z0-9_]*\s*=\s*["']([^"']+)["']/gm)].map(
      (match) => match[1]
    )
    return [...new Set(values)].sort()
  } catch {
    return []
  }
}

export function messagingStatus(repoRoot: string | null): MessagingStatus {
  const preferences = readMessagingPreferences()
  const sourceRoot = messagingSourceRoot(repoRoot)
  const installed = Boolean(
    sourceRoot &&
      existsSync(join(sourceRoot, 'pyproject.toml')) &&
      existsSync(join(sourceRoot, 'gateway', 'run.py'))
  )
  return {
    ...preferences,
    installed,
    sourceRoot,
    sourceCommit: MESSAGING_SOURCE_COMMIT,
    platforms: installed ? messagingPlatforms(sourceRoot) : [],
    configured: existsSync(join(preferences.home, 'config.yaml')),
    setupCommand: sourceRoot
      ? `uv run --project "${sourceRoot}" hermes setup`
      : 'Messaging source is not installed'
  }
}

export function shouldStartMessaging(status: MessagingStatus): boolean {
  return status.installed && status.configured && status.enabled
}

export function messagingEnvironment(home: string, parentPid: number): Record<string, string> {
  return {
    HERMES_HOME: home,
    MARVI_PARENT_PID: String(parentPid),
    // The upstream gateway has its own restart machinery. Electron is the
    // owner here, so it must exit back to our supervisor instead.
    HERMES_GATEWAY_EXTERNAL_SUPERVISOR: '1'
  }
}

/** Open the upstream interactive setup unchanged. Credentials are entered in
 * that process and written to its private home; they never cross renderer IPC. */
export function launchMessagingSetup(
  uv: string,
  repoRoot: string | null,
  parentPid: number
): boolean {
  const status = messagingStatus(repoRoot)
  if (!status.installed) return false
  mkdirSync(status.home, { recursive: true })
  try {
    const child = spawn(uv, ['run', '--project', status.sourceRoot, 'hermes', 'setup'], {
      cwd: status.sourceRoot,
      detached: true,
      stdio: 'inherit',
      windowsHide: false,
      env: { ...process.env, ...messagingEnvironment(status.home, parentPid) }
    })
    child.unref()
    return true
  } catch {
    return false
  }
}
