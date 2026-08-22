import { atom } from 'nanostores'

/**
 * What is being said, right now, as subtitles.
 *
 * The transcript already reached the window — by riding the runtime poll, which
 * runs every two seconds. That is fine for "is the Gateway up" and useless for
 * this: words arrive from the recogniser several times a second, and a poll two
 * seconds wide turns a sentence appearing word by word into a paragraph landing
 * whole, twice, after the moment it described.
 *
 * LiveKit already publishes both sides into the room as a text stream on
 * `lk.transcription`, with the sender's identity on it and a flag saying whether
 * a segment is final. That is the same data without the wait, so this store is
 * fed straight from the room and the polled copy is left to the places that only
 * need a summary.
 */

/** The topic LiveKit's agents publish transcription on. */
export const TRANSCRIPTION_TOPIC = 'lk.transcription'
/** Attributes it carries. `final` distinguishes a settled segment from a guess. */
export const ATTR_FINAL = 'lk.transcription_final'
export const ATTR_SEGMENT = 'lk.segment_id'

export interface Line {
  /** Who said it. The agent's line is the reply; anything else is the user. */
  role: 'user' | 'marvi'
  text: string
  /** False while the recogniser may still revise it. */
  final: boolean
  /** Stable across the revisions of one segment, so React can keep the node. */
  id: string
}

/**
 * The last thing each side said, and nothing before it.
 *
 * Two lines at most, because this is a glance while talking rather than a
 * record — Chat is where a transcript belongs. Keeping more would also mean
 * deciding when to scroll it, and subtitles that scroll are a transcript.
 */
export const $heard = atom<Line | null>(null)
export const $spoken = atom<Line | null>(null)

export function applyTranscript(line: Line): void {
  const store = line.role === 'user' ? $heard : $spoken
  const current = store.get()
  // A segment revises itself: the recogniser sends its best guess and then
  // sends it again, longer. Replacing on a matching id is what makes the line
  // grow in place instead of stuttering between two versions.
  if (current && current.id === line.id) {
    store.set({ ...current, text: line.text, final: line.final })
    return
  }
  store.set(line)
}

/** Clear both lines. Leaving the last exchange on screen after the call ended
 *  reads as though Marvi is still saying it. */
export function clearTranscript(): void {
  $heard.set(null)
  $spoken.set(null)
}
