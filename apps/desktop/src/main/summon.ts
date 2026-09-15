/**
 * A key combination that does what the wake word does.
 *
 * The wake word was the only hands-free way in, and it is the one that fails
 * first: a noisy room, a headset on, a call in progress. The hotkey calls the
 * same `requestWakeJoin` the wake listener's `--wake` launch does, so there is
 * one path into a voice session, not two.
 *
 * `MARVI_SUMMON_HOTKEY` is an Electron accelerator (`Alt+Shift+M`,
 * `CommandOrControl+Space`); `off` turns it off.
 */
export const DEFAULT_SUMMON_HOTKEY = 'Alt+Shift+M'

const OFF = new Set(['', 'off', 'none', '0', 'false'])

export function summonAccelerator(env: NodeJS.ProcessEnv = process.env): string | null {
  const raw = (env['MARVI_SUMMON_HOTKEY'] ?? DEFAULT_SUMMON_HOTKEY).trim()
  return OFF.has(raw.toLowerCase()) ? null : raw
}
