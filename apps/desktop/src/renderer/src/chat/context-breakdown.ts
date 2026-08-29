import type { ChatContext } from '../../../shared/runtime'

export interface ContextSegment {
  id: 'prompt' | 'cached' | 'reserve' | 'available'
  label: string
  tokens: number
}

export function contextPercent(context?: ChatContext | null): number | null {
  if (!context?.context_window) return null
  return Math.min(100, Math.round((context.input_tokens / context.context_window) * 100))
}

export function contextSegments(context?: ChatContext | null): ContextSegment[] {
  if (!context?.context_window) return []

  const window = context.context_window
  const used = Math.min(window, Math.max(0, context.input_tokens))
  const cached = Math.min(used, Math.max(0, context.cached_tokens))
  const prompt = Math.max(0, used - cached)
  const reserve = Math.min(Math.max(0, window - used), Math.max(0, context.reply_reserve))
  const available = Math.max(0, window - used - reserve)

  return [
    { id: 'prompt', label: 'Prompt', tokens: prompt },
    { id: 'cached', label: 'Cached', tokens: cached },
    { id: 'reserve', label: 'Reply reserve', tokens: reserve },
    { id: 'available', label: 'Available', tokens: available }
  ]
}

export function compactTokens(value: number): string {
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
