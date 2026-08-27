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

/**
 * How much of a line a subtitle shows.
 *
 * A glance, not a transcript -- the component says so and the layout assumed
 * it. Nothing enforced it, so a long answer wrapped line after line until it
 * filled the window and covered the orb it was supposed to caption.
 *
 * ## Whole sentences, counted from the end
 *
 * The tail rather than the head, because this is live text and the words being
 * said right now are the ones worth reading. Chat has the rest.
 *
 * But a tail measured in characters cuts wherever the budget lands, and a subtitle
 * that opens mid-clause reads as damage rather than as continuation: "...
 * running perfectly. Presence is detected via the sensor" is a fragment of a
 * sentence nobody can see the start of. So the cut is made at sentence
 * boundaries and the character budget only decides how many sentences fit.
 *
 * The sentence being spoken is always kept whole, even alone. Only when that
 * one sentence is longer than the entire budget does this fall back to cutting
 * inside it -- and then it says so.
 */
//: Sized to the box it goes in: the line is `min(46ch, 100%)` wide and clamped
//: to three of them, so anything past about 130 characters is cut by the CSS
//: without anybody deciding where. This decides instead, one line short of the
//: clamp.
export const SUBTITLE_CHARS = 120

/** After `.`, `!`, `?` or an ellipsis, at a space. Keeps the punctuation. */
const SENTENCE_END = /(?<=[.!?…])\s+/

export function subtitleTail(text: string): string {
  const compact = text.replace(/\s+/g, ' ').trim()
  if (compact.length <= SUBTITLE_CHARS) return compact

  const sentences = compact.split(SENTENCE_END)
  // The last one is in progress; it is the subtitle whatever its length.
  let shown = sentences.pop() ?? ''
  while (sentences.length) {
    const earlier = sentences[sentences.length - 1]
    if (earlier.length + 1 + shown.length > SUBTITLE_CHARS) break
    shown = `${sentences.pop()} ${shown}`
  }
  if (shown.length <= SUBTITLE_CHARS) return shown

  // One sentence, longer than the budget. Cut it at a word, and mark the cut.
  const cut = shown.slice(-SUBTITLE_CHARS)
  const space = cut.indexOf(' ')
  return `… ${space >= 0 ? cut.slice(space + 1) : cut}`
}
