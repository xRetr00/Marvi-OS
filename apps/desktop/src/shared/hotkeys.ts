/**
 * Every global key combination Marvi answers to, and the rules for writing one.
 *
 * Global hotkeys belong to Electron main (it owns Windows lifecycle), but the
 * settings window has to show and edit them, so everything that does not need
 * `electron` lives here and is shared by main, the preload bridge and the
 * renderer.
 *
 * A binding is an Electron accelerator: modifiers and one key, joined by `+`.
 * Two rules are enforced rather than trusted:
 *
 * * **At least one modifier.** A bare `M` registered globally swallows the
 *   letter in every other application on the machine -- including the one the
 *   user is typing into. There is no undo for that from inside Marvi.
 * * **One key.** `Alt+Shift+M+K` is not an accelerator; Electron accepts the
 *   string and then behaves unpredictably, which is worse than refusing it.
 */

export type HotkeyAction = 'summon' | 'stop' | 'chat' | 'window' | 'hotkeys'

export interface HotkeyDefinition {
  id: HotkeyAction
  label: string
  description: string
  fallback: string
}

/** The order the shortcuts window lists them in. */
export const HOTKEY_DEFINITIONS: readonly HotkeyDefinition[] = [
  {
    id: 'summon',
    label: 'Talk to Marvi',
    description: 'Starts a voice session, exactly as the wake word does.',
    fallback: 'Alt+Shift+M'
  },
  {
    id: 'stop',
    label: 'Stop talking',
    description: 'Stops whatever Marvi is saying, like Stop on the Island.',
    fallback: 'Alt+Shift+S'
  },
  {
    id: 'chat',
    label: 'Open Chat',
    description: 'Brings the window forward on the Chat page.',
    fallback: 'Alt+Shift+C'
  },
  {
    id: 'window',
    label: 'Show or hide Marvi',
    description: 'Brings the window forward, or hides it when it already has focus.',
    fallback: 'Alt+Shift+W'
  },
  {
    id: 'hotkeys',
    label: 'Open this window',
    description: 'Opens the keyboard shortcuts window from anywhere.',
    fallback: 'Alt+Shift+K'
  }
] as const

export const HOTKEY_ACTIONS: readonly HotkeyAction[] = HOTKEY_DEFINITIONS.map((one) => one.id)

export type HotkeyBindings = Record<HotkeyAction, string>

/** What the window gets back from main: the state plus, on a rejected edit,
 *  the reason it was rejected. */
export interface HotkeyReport extends HotkeyState {
  error?: string
}

/** What the bindings look like after Marvi has tried to register them. */
export interface HotkeyState {
  bindings: HotkeyBindings
  /** Action id -> why it is not active right now. Absent when it is. */
  problems: Partial<Record<HotkeyAction, string>>
}

const MODIFIERS = new Map<string, string>([
  ['command', 'Command'],
  ['cmd', 'Command'],
  ['control', 'Control'],
  ['ctrl', 'Control'],
  ['commandorcontrol', 'CommandOrControl'],
  ['cmdorctrl', 'CommandOrControl'],
  ['alt', 'Alt'],
  ['option', 'Option'],
  ['altgr', 'AltGr'],
  ['shift', 'Shift'],
  ['super', 'Super'],
  ['meta', 'Meta'],
  ['win', 'Super'],
  ['windows', 'Super']
])

/** Modifier order Windows itself prints, so two people writing the same
 *  combination store the same string and a clash is detectable. */
const MODIFIER_ORDER = [
  'CommandOrControl',
  'Command',
  'Control',
  'Alt',
  'AltGr',
  'Option',
  'Shift',
  'Super',
  'Meta'
]

const NAMED_KEYS = new Map<string, string>(
  [
    'Plus',
    'Space',
    'Tab',
    'Backspace',
    'Delete',
    'Insert',
    'Return',
    'Enter',
    'Up',
    'Down',
    'Left',
    'Right',
    'Home',
    'End',
    'PageUp',
    'PageDown',
    'Escape',
    'VolumeUp',
    'VolumeDown',
    'VolumeMute',
    'MediaNextTrack',
    'MediaPreviousTrack',
    'MediaStop',
    'MediaPlayPause',
    'PrintScreen'
  ].map((key) => [key.toLowerCase(), key])
)

/** The punctuation Electron accepts as a key, as its own characters. */
const PUNCTUATION = new Set([
  '~',
  '`',
  '!',
  '@',
  '#',
  '$',
  '%',
  '^',
  '&',
  '*',
  '(',
  ')',
  '-',
  '_',
  '=',
  '[',
  ']',
  '{',
  '}',
  '\\',
  '|',
  ';',
  ':',
  "'",
  '"',
  ',',
  '<',
  '.',
  '>',
  '/',
  '?'
])

function tidyKey(raw: string): string {
  const lower = raw.toLowerCase()
  if (NAMED_KEYS.has(lower)) return NAMED_KEYS.get(lower) as string
  if (lower === 'esc') return 'Escape'
  if (/^f([1-9]|1[0-9]|2[0-4])$/.test(lower)) return lower.toUpperCase()
  if (/^num[0-9]$/.test(lower)) return lower
  if (/^[a-z0-9]$/.test(lower)) return lower.toUpperCase()
  if (raw.length === 1 && PUNCTUATION.has(raw)) return raw
  return ''
}

/**
 * The canonical spelling of an accelerator, or '' when it is not one.
 * `alt+shift+m`, `Shift+Alt+M` and `ALT + SHIFT + m` all become `Alt+Shift+M`.
 */
export function tidy(accelerator: string): string {
  const parts = String(accelerator ?? '')
    .split('+')
    .map((part) => part.trim())
    .filter(Boolean)
  if (parts.length < 2) return ''
  const modifiers = new Set<string>()
  const keys: string[] = []
  for (const part of parts) {
    const modifier = MODIFIERS.get(part.toLowerCase())
    if (modifier) {
      modifiers.add(modifier)
      continue
    }
    const key = tidyKey(part)
    if (!key) return ''
    keys.push(key)
  }
  if (keys.length !== 1 || modifiers.size === 0) return ''
  const ordered = MODIFIER_ORDER.filter((name) => modifiers.has(name))
  return [...ordered, keys[0]].join('+')
}

/** '' when the accelerator is usable, otherwise why it is not. */
export function why(accelerator: string): string {
  const raw = String(accelerator ?? '').trim()
  if (!raw) return ''
  if (tidy(raw)) return ''
  const parts = raw
    .split('+')
    .map((part) => part.trim())
    .filter(Boolean)
  if (parts.length < 2) return 'Hold a modifier too — Ctrl, Alt, Shift or Win.'
  return 'Windows cannot register that combination.'
}

/** The bindings a fresh install gets. `MARVI_SUMMON_HOTKEY` still chooses the
 *  summon default, as it did before there was a shortcuts window; `off`
 *  disables it. A binding saved in the window wins over both. */
export function defaults(env: Record<string, string | undefined> = {}): HotkeyBindings {
  const bindings = {} as HotkeyBindings
  for (const definition of HOTKEY_DEFINITIONS) bindings[definition.id] = definition.fallback
  const summon = (env['MARVI_SUMMON_HOTKEY'] ?? '').trim()
  if (summon) {
    bindings.summon = ['off', 'none', '0', 'false'].includes(summon.toLowerCase())
      ? ''
      : tidy(summon) || bindings.summon
  }
  return bindings
}

/** Bindings read back from disk: unknown actions dropped, unusable
 *  accelerators replaced by the default rather than silently lost. */
export function normalize(
  stored: unknown,
  env: Record<string, string | undefined> = {}
): HotkeyBindings {
  const bindings = defaults(env)
  if (!stored || typeof stored !== 'object') return bindings
  for (const definition of HOTKEY_DEFINITIONS) {
    const raw = (stored as Record<string, unknown>)[definition.id]
    if (typeof raw !== 'string') continue
    if (!raw.trim()) {
      bindings[definition.id] = '' // deliberately switched off
      continue
    }
    const clean = tidy(raw)
    if (clean) bindings[definition.id] = clean
  }
  return bindings
}

/** Actions sharing one combination. Windows gives a combination to whoever
 *  registered it first, so the second would be dead without this. */
export function clashes(bindings: HotkeyBindings): HotkeyAction[] {
  const seen = new Map<string, HotkeyAction>()
  const clashing: HotkeyAction[] = []
  for (const action of HOTKEY_ACTIONS) {
    const accelerator = bindings[action]
    if (!accelerator) continue
    if (seen.has(accelerator)) clashing.push(action)
    else seen.set(accelerator, action)
  }
  return clashing
}

/** The accelerator a key press means, or '' while only modifiers are held. */
export function acceleratorFrom(event: {
  key: string
  code?: string
  ctrlKey: boolean
  altKey: boolean
  shiftKey: boolean
  metaKey: boolean
}): string {
  const modifiers: string[] = []
  if (event.ctrlKey) modifiers.push('Control')
  if (event.altKey) modifiers.push('Alt')
  if (event.shiftKey) modifiers.push('Shift')
  if (event.metaKey) modifiers.push('Super')
  // `event.key` is what Shift produced ('M', '%'); the physical key is what a
  // person means by "Alt+Shift+5", so the code wins when there is one.
  const code = event.code ?? ''
  let key = event.key
  if (/^Key[A-Z]$/.test(code)) key = code.slice(3)
  else if (/^Digit[0-9]$/.test(code)) key = code.slice(5)
  else if (/^Numpad[0-9]$/.test(code)) key = code.toLowerCase().replace('numpad', 'num')
  if (['Control', 'Alt', 'Shift', 'Meta', 'CapsLock', 'AltGraph'].includes(key)) return ''
  if (key === ' ') key = 'Space'
  return tidy([...modifiers, key].join('+'))
}
