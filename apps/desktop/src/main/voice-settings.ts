/** Whether saved settings change models owned by the voice worker. */
export function requiresVoiceWorkerRestart(values: unknown): boolean {
  if (!values || typeof values !== 'object' || Array.isArray(values)) return false
  return Object.keys(values).some(
    (name) => name.startsWith('MARVI_STT_') || name.startsWith('MARVI_TTS_')
  )
}
