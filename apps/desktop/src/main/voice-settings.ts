/** Whether saved settings change models owned by the voice worker. */
export function requiresVoiceWorkerRestart(values: unknown): boolean {
  if (!values || typeof values !== 'object' || Array.isArray(values)) return false
  return Object.keys(values).some(
    (name) => name.startsWith('MARVI_STT_') || name.startsWith('MARVI_TTS_')
  )
}

/**
 * How long to wait for the person to stop changing things before restarting.
 *
 * Every voice-related `PUT /providers/settings` restarted the agent, and the
 * settings page writes one PUT per field. Choosing an engine and then a voice
 * for it is two; a few seconds of fiddling is four. From one afternoon:
 *
 *     12:01:49  PUT /providers/settings   -> restart, 30-50s prewarm
 *     12:01:54  PUT /providers/settings   -> restart, again
 *     12:02:16  PUT /providers/settings   -> restart, again
 *     12:02:20  PUT /providers/settings   -> restart, again
 *     12:02:23  POST /livekit/session     <- Join, 3s into the last prewarm
 *
 * and that Join is the "no agent joined" -- the worker had been torn down
 * three seconds earlier and was thirty seconds from registering. Restarting
 * Marvi "fixed" it only because by then the prewarm had finished.
 *
 * Four seconds is longer than the gap between two fields of one decision and
 * far shorter than the prewarm it is protecting, so a burst of edits costs one
 * restart instead of four, and the restart begins once the person has actually
 * finished choosing.
 */
export const SETTLE_MS = 4_000

let pending: ReturnType<typeof setTimeout> | null = null

/**
 * Restart the voice worker once, after the edits stop.
 *
 * Exported with the timer visible so a test can drive it; `restartWhenSettled`
 * is the only thing that should schedule this.
 */
export function restartWhenSettled(restart: () => void, delay: number = SETTLE_MS): void {
  if (pending) clearTimeout(pending)
  pending = setTimeout(() => {
    pending = null
    restart()
  }, delay)
}

/** Drop any pending restart. For tests, and for shutdown. */
export function cancelSettledRestart(): void {
  if (pending) clearTimeout(pending)
  pending = null
}
