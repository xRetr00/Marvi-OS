/**
 * Where Marvi has been this session: the pages and the files.
 *
 * Derived from the tool calls rather than reported separately, because the
 * calls already carry it — `web_fetch` has a url, `file_read` has a path — and
 * a second stream saying the same thing is a second thing that can disagree
 * with the first.
 *
 * The tool list answers "what did she do". This answers "what did she look
 * at", which is the question you ask when an answer surprises you.
 */
import type { VoiceCall } from './voice-cards'

export interface Source {
  kind: 'web' | 'file'
  /** What to show: a hostname, or a filename. Short enough for a card. */
  label: string
  /** The whole thing, for the title attribute. */
  full: string
  /** How many calls touched it, so a page read three times says so. */
  times: number
}

/** Argument names that carry a place rather than a value. */
const PLACES = ['url', 'path', 'file', 'link', 'href', 'query']

function hostOf(value: string): string {
  try {
    const parsed = new URL(value)
    return parsed.hostname.replace(/^www\./, '')
  } catch {
    return value
  }
}

function nameOf(value: string): string {
  // Both separators, because a path from the model may be either and this
  // runs on Windows where the answer is "both".
  const parts = value.split(/[\\/]/)
  return parts.at(-1) || value
}

/**
 * The distinct places a session touched, most recent first.
 *
 * A search query counts as a source, which is a deliberate stretch: "she
 * searched for X" is the same kind of fact as "she read Y", and leaving it out
 * made the list look emptier than the session was.
 */
export function sourcesFrom(calls: VoiceCall[], limit = 8): Source[] {
  const found = new Map<string, Source>()
  for (const call of calls) {
    if (call.outcome === 'failed') continue
    for (const [name, raw] of Object.entries(call.arguments ?? {})) {
      if (!PLACES.includes(name.toLowerCase())) continue
      const value = String(raw ?? '').trim()
      if (!value || value.length > 300) continue
      const web = /^https?:\/\//i.test(value) || name.toLowerCase() === 'query'
      const key = `${web ? 'web' : 'file'}:${value}`
      const already = found.get(key)
      if (already) {
        already.times += 1
        continue
      }
      found.set(key, {
        kind: web ? 'web' : 'file',
        label: (web ? hostOf(value) : nameOf(value)).slice(0, 40),
        full: value,
        times: 1
      })
    }
  }
  // `calls` arrives newest first, so insertion order already is.
  return [...found.values()].slice(0, limit)
}
