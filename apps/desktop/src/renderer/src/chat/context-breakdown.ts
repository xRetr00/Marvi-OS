import type { ChatContext } from '../../../shared/runtime'

export interface ContextSegment {
  id: 'prompt' | 'cached' | 'reserve' | 'available'
  label: string
  tokens: number
}

function safe(value: number): number {
  return Number.isFinite(value) ? Math.max(0, value) : 0
}

export function contextPercent(context?: ChatContext | null): number | null {
  const window = safe(context?.context_window ?? 0)
  if (!window) return null
  return Math.min(100, Math.round((safe(context?.input_tokens ?? 0) / window) * 100))
}

export function contextSegments(context?: ChatContext | null): ContextSegment[] {
  if (!safe(context?.context_window ?? 0)) return []

  const source = context as ChatContext
  const window = safe(source.context_window)
  const used = Math.min(window, safe(source.input_tokens))
  const cached = Math.min(used, safe(source.cached_tokens))
  const prompt = Math.max(0, used - cached)
  const reserve = Math.min(Math.max(0, window - used), safe(source.reply_reserve))
  const available = Math.max(0, window - used - reserve)

  return [
    { id: 'prompt', label: 'Prompt', tokens: prompt },
    { id: 'cached', label: 'Cached', tokens: cached },
    { id: 'reserve', label: 'Reply reserve', tokens: reserve },
    { id: 'available', label: 'Available', tokens: available }
  ]
}

export function contextMeterCells(
  context?: ChatContext | null,
  count = 12
): Array<ContextSegment['id'] | 'unknown'> {
  const segments = contextSegments(context)
  const window = safe(context?.context_window ?? 0)
  if (!segments.length || !window) return Array.from({ length: count }, () => 'unknown')
  const boundaries = segments.reduce<number[]>((values, segment) => {
    values.push((values.at(-1) ?? 0) + segment.tokens)
    return values
  }, [])
  return Array.from({ length: count }, (_, index) => {
    const midpoint = ((index + 0.5) / count) * window
    return segments[boundaries.findIndex((boundary) => midpoint <= boundary)]?.id ?? 'available'
  })
}

export function compactTokens(value: number): string {
  value = safe(value)
  if (value >= 1_000_000) {
    const scaled = value / 1_000_000
    return `${scaled.toFixed(scaled >= 10 || Number.isInteger(scaled) ? 0 : 1)}m`
  }
  if (value >= 1_000) {
    const scaled = value / 1_000
    return `${scaled.toFixed(scaled >= 10 || Number.isInteger(scaled) ? 0 : 1)}k`
  }
  return value.toLocaleString()
}
