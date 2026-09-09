/**
 * Questions Marvi has put on screen, and what the user did with them.
 *
 * Mirrors `marvi_gateway.asking`. The states are the Gateway's, spelled the
 * same way, because a second vocabulary for the same six things is how the two
 * halves drift apart.
 */

/** What the desktop is allowed to report back. */
export type Settled = 'answered' | 'dismissed' | 'declined'

export interface Question {
  id: string
  question: string
  /** What it is about, so the answer can be filed. Free text. */
  about: string
  /** A hint for the empty box. Never an answer. */
  placeholder: string
  state: string
  answer: string
  asked_at: number
  settled_at: number
}

export interface Asking {
  /** On screen right now, oldest first. */
  waiting: Question[]
  /** Closed or ignored — questions Marvi still owes them out loud. */
  owed_aloud: Question[]
}
