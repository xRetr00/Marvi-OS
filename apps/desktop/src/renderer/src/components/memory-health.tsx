/**
 * Where Marvi's memories came from, and which of them are not memories.
 *
 * The store was 199 entries and looked fine as a list. Read by source it was
 * not: 55 of them came from the per-turn extractor and most of those were
 * things like
 *
 *     User's greeting and status
 *     "The user said 'Yeah, I was wondering I was going on.' which Marvi
 *      interpreted as a greeting or status update."
 *
 * every one built out of a misheard sentence, and every one coming back on
 * recall as though it bore on the turn. The same store's dreaming pass had
 * written "Shereef uses Home Assistant and has a RGBCW lightbulb (entity_id
 * light.rgbcw_lightbulb)" -- which is what a memory is supposed to look like.
 *
 * A flat list cannot show that difference and a bar by source can, which is
 * the whole reason this exists. The store now refuses the narrating kind on
 * the way in; this is how you see whether it is working, and what is still
 * left over from before it did.
 */
import { AlertTriangle, Database, Layers, Sparkles } from 'lucide-react'
import React, { useMemo } from 'react'

import type { MemoryEntry, MemoryPage } from '../../../shared/runtime'

/**
 * A body that describes the conversation instead of the world.
 *
 * Deliberately the same rule as `remembering.NARRATES_THE_EXCHANGE` on the
 * Gateway, and deliberately about a *speech act* rather than the word
 * "assistant": "the backend infrastructure of the assistant system is named
 * Hermes" is a fact, and a broader pattern threw it away.
 */
const NARRATES =
  /\bthe (?:user|assistant) (?:said|asked|replied|responded|confirmed|mentioned|stated|indicated|greeted|told)\b|\b(?:which|this) indicates\b|\bmarvi (?:interpreted|responded|replied|said)\b/i

/** How each source is described, for people who did not write the code. */
const SOURCE_MEANS: Record<string, string> = {
  marvi: 'written during a conversation',
  dreaming: 'worked out overnight',
  reflection: 'noticed by repetition',
  conclusion: 'concluded from other memories'
}

function describeSource(source: string): string {
  if (source.startsWith('import:')) return 'imported'
  if (source.startsWith('composio:')) return 'from a connected account'
  return SOURCE_MEANS[source] ?? source
}

function shortSource(source: string): string {
  if (source.startsWith('import:')) return source.slice(7).split('/')[0].slice(0, 18)
  if (source.startsWith('composio:')) return source.split(':')[1] ?? 'account'
  return source
}

/** Marvi's own sources: what she wrote down, worked out, or noticed. */
const LEARNED_FROM = new Set(['marvi', 'dreaming', 'reflection', 'conclusion'])
/** "Recently" is three days: long enough to span a night's dreaming. */
const RECENT_MS = 3 * 24 * 60 * 60 * 1000

/**
 * What she learned lately, newest first.
 *
 * Learning happened and nothing showed it. The per-turn writer, the overnight
 * dreaming pass and the repetition pass all wrote into this store, and the page
 * only ever offered a count by source and a flat list sorted however the store
 * returned it -- so "she worked out that Shereef sleeps in the mornings" was
 * indistinguishable from the 170 things she already knew.
 */
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

function when(at: string): string {
  const moment = new Date(at)
  const today = moment.toDateString() === new Date().toDateString()
  return moment.toLocaleString(
    undefined,
    today ? { hour: '2-digit', minute: '2-digit' } : { weekday: 'short', hour: '2-digit', minute: '2-digit' }
  )
}

export function MemoryHealth({ page }: { page: MemoryPage }): React.JSX.Element {
  const entries = page.entries
  const learned = useMemo(() => recentlyLearned(entries), [entries])

  const bySource = useMemo(() => {
    const counts = new Map<string, { total: number; narrating: number }>()
    for (const entry of entries) {
      const found = counts.get(entry.source) ?? { total: 0, narrating: 0 }
      found.total += 1
      if (NARRATES.test(entry.body)) found.narrating += 1
      counts.set(entry.source, found)
    }
    return [...counts.entries()]
      .map(([source, counts]) => ({ source, ...counts }))
      .sort((a, b) => b.total - a.total)
  }, [entries])

  const narrating = useMemo(
    () => entries.filter((entry: MemoryEntry) => NARRATES.test(entry.body)),
    [entries]
  )
  const episodic = entries.filter((entry) => entry.kind === 'episodic').length
  const biggest = Math.max(1, ...bySource.map((row) => row.total))

  return (
    <section className="mem-health">
      <h3>
        <Database aria-hidden="true" /> What is in here
      </h3>
      <p className="mem-health-sub">
        {page.total} memories · {entries.length - episodic} facts, {episodic} moments ·{' '}
        {page.summary.graph?.entities ?? 0} entities and {page.summary.graph?.relations ?? 0}{' '}
        relationships between them
      </p>

      {/* By source, because that is the axis the difference shows up on. */}
      <ul className="mem-sources">
        {bySource.map((row) => (
          <li key={row.source}>
            <span className="mem-source-name" title={row.source}>
              {shortSource(row.source)}
            </span>
            <span className="mem-source-bar">
              <i style={{ width: `${(row.total / biggest) * 100}%` }} />
              {row.narrating > 0 && (
                <i
                  className="is-narrating"
                  style={{ width: `${(row.narrating / biggest) * 100}%` }}
                  title={`${row.narrating} describe the conversation rather than a fact`}
                />
              )}
            </span>
            <span className="mem-source-count">{row.total}</span>
            <span className="mem-source-means">{describeSource(row.source)}</span>
          </li>
        ))}
      </ul>

      {narrating.length > 0 && (
        <div className="mem-warning">
          <AlertTriangle aria-hidden="true" />
          <div>
            <strong>
              {narrating.length} of these describe the conversation rather than a fact
            </strong>
            <p>
              They came in before the store started refusing them, and each one still comes back on
              recall as though it bore on the turn.
            </p>
            <ul>
              {narrating.slice(0, 4).map((entry) => (
                <li key={entry.id}>
                  <span>{entry.subject}</span>
                  <em>{entry.body.slice(0, 96)}…</em>
                </li>
              ))}
            </ul>
            {narrating.length > 4 && <small>and {narrating.length - 4} more</small>}
          </div>
        </div>
      )}

      <div className="mem-learned">
        <h4>
          <Sparkles aria-hidden="true" /> Recently learned
        </h4>
        {learned.length === 0 ? (
          <p className="mem-learned-empty">Nothing new in the last three days.</p>
        ) : (
          <ul>
            {learned.map((entry) => (
              <li key={entry.id}>
                <span className="mem-learned-how">
                  {describeSource(entry.source)} · {when(entry.at)}
                </span>
                <strong>{entry.subject}</strong>
                <em>{entry.body.slice(0, 160)}</em>
              </li>
            ))}
          </ul>
        )}
      </div>

      {(page.summary.facts ?? []).length > 0 && (
        <div className="mem-facts">
          <Layers aria-hidden="true" />
          <span>{(page.summary.facts ?? []).join(' · ')}</span>
        </div>
      )}
    </section>
  )
}
