/**
 * Registering Marvi's global hotkeys, and keeping them on disk.
 *
 * The rules and the shape live in `shared/hotkeys.ts` because the shortcuts
 * window edits them too; this is the half that needs Electron and the file
 * system: read `hotkeys.json`, register what it says, and report back what
 * Windows refused so the window can say "another app has that one" instead of
 * a key that silently does nothing.
 *
 * Every hotkey is registered through one function, so a change is
 * unregister-all-then-register rather than a diff -- five accelerators cost
 * nothing to re-register and a diff is a bug waiting for the day two actions
 * swap combinations.
 */
import { globalShortcut } from 'electron'
import { mkdirSync, readFileSync, writeFileSync } from 'fs'
import { join } from 'path'

import {
  HOTKEY_ACTIONS,
  type HotkeyAction,
  type HotkeyBindings,
  type HotkeyState,
  clashes,
  defaults,
  normalize,
  tidy,
  why
} from '../shared/hotkeys'

export function hotkeysPath(stateDirectory: string): string {
  return join(stateDirectory, 'hotkeys.json')
}

export function load(stateDirectory: string, env = process.env): HotkeyBindings {
  try {
    return normalize(JSON.parse(readFileSync(hotkeysPath(stateDirectory), 'utf8')), env)
  } catch {
    return defaults(env)
  }
}

export function save(stateDirectory: string, bindings: HotkeyBindings): void {
  mkdirSync(stateDirectory, { recursive: true })
  writeFileSync(
    hotkeysPath(stateDirectory),
    `${JSON.stringify(bindings, null, 2)}\n`,
    'utf8'
  )
}

/** One accelerator changed. Returns the whole set, so a caller never has to
 *  merge -- and an unusable accelerator is refused rather than stored. */
export function withBinding(
  bindings: HotkeyBindings,
  action: HotkeyAction,
  accelerator: string
): { bindings: HotkeyBindings; error: string } {
  if (!HOTKEY_ACTIONS.includes(action)) return { bindings, error: 'No such shortcut.' }
  const raw = String(accelerator ?? '').trim()
  if (!raw) return { bindings: { ...bindings, [action]: '' }, error: '' }
  const clean = tidy(raw)
  if (!clean) return { bindings, error: why(raw) }
  const next = { ...bindings, [action]: clean }
  const taken = HOTKEY_ACTIONS.find((other) => other !== action && next[other] === clean)
  if (taken) return { bindings, error: `Already used by "${taken}".` }
  return { bindings: next, error: '' }
}

type Handlers = Partial<Record<HotkeyAction, () => void>>

/**
 * Register the lot. Anything Windows refuses -- usually because another
 * application got there first -- comes back as a problem rather than an
 * exception, because four working hotkeys and one explained failure is a
 * better outcome than none.
 */
export function apply(bindings: HotkeyBindings, handlers: Handlers): HotkeyState {
  globalShortcut.unregisterAll()
  const problems: Partial<Record<HotkeyAction, string>> = {}
  const clashing = new Set(clashes(bindings))
  for (const action of HOTKEY_ACTIONS) {
    const accelerator = bindings[action]
    const handler = handlers[action]
    if (!accelerator || !handler) continue
    if (clashing.has(action)) {
      problems[action] = 'Another Marvi shortcut already uses this.'
      continue
    }
    let registered = false
    try {
      registered = globalShortcut.register(accelerator, handler)
    } catch (error) {
      problems[action] = error instanceof Error ? error.message : 'Windows refused it.'
      continue
    }
    if (!registered) problems[action] = 'Another app is using this combination.'
  }
  return { bindings, problems }
}

export function release(): void {
  globalShortcut.unregisterAll()
}
