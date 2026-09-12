import type { MemoryEntry } from '../../../shared/runtime'

/** Marvi's own sources: what she wrote down, worked out, or noticed. */
const LEARNED_FROM = new Set(['marvi', 'dreaming', 'reflection', 'conclusion'])
/** "Recently" is three days: long enough to span a night's dreaming. */
const RECENT_MS = 3 * 24 * 60 * 60 * 1000

/** What she learned lately, newest first. */
export function recentlyLearned(entries: MemoryEntry[], now: number = Date.now()): MemoryEntry[] {
  return entries
    .filter((entry) => LEARNED_FROM.has(entry.source))
    .filter((entry) => {
      const at = Date.parse(entry.at)
      return !Number.isNaN(at) && now - at <= RECENT_MS
    })
    .sort((a, b) => Date.parse(b.at) - Date.parse(a.at))
    .slice(0, 8)
}
