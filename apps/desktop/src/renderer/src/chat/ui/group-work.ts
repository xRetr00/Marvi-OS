/**
 * Which parts of a reply are the *work* and which are the *answer*.
 *
 * Thoughts, commentary and tool calls are the work: they collapse into one
 * "Marvi worked for Ns" disclosure above the reply. The answer text, widgets,
 * question cards and sources stay outside it, because they are what the reply
 * is -- a widget folded away inside the work log is a widget nobody sees, and
 * a question card folded away is a turn blocked on something invisible.
 *
 * Defined at module scope rather than inline: `GroupedParts` fingerprints its
 * `groupBy`, and a fresh function each render rebuilds the grouping tree every
 * time a streamed token lands.
 */

import type { PartState } from '@assistant-ui/react'

import { ASK_TOOL, DELEGATE_TOOL, WIDGET_TOOL } from '../runtime/convert'

export type WorkGroup = 'group-work'

const WORK: readonly WorkGroup[] = ['group-work']

export function groupWork(part: PartState): readonly WorkGroup[] | null {
  switch (part.type) {
    case 'reasoning':
      return WORK
    case 'data':
      return part.name === 'commentary' ? WORK : null
    case 'tool-call':
      // Tools with a face of their own are part of the answer, not the work.
      // A sub-agent's card is one: it goes on working after the reply ends,
      // and folded into the work log nobody would see it finish.
      return part.toolName === WIDGET_TOOL ||
        part.toolName === ASK_TOOL ||
        part.toolName === DELEGATE_TOOL
        ? null
        : WORK
    default:
      return null
  }
}

/** "12s", "1m 5s", "2m". A work log is read at a glance, not measured. */
export function formatWorked(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000))
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return rest ? `${minutes}m ${rest}s` : `${minutes}m`
}
