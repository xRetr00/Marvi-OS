export function activitySeconds(startedAt: string, now = Date.now()): number {
  const started = Date.parse(startedAt)
  if (!Number.isFinite(started)) return 0
  return Math.max(0, Math.floor((now - started) / 1000))
}

export function formatActivityTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  return minutes > 0 ? `${minutes}:${String(remainder).padStart(2, '0')}` : `${remainder}s`
}
