/**
 * The `@` being typed at the end of the composer, and completing it.
 *
 * Only the trailing mention, deliberately. Reading the caret means holding a
 * ref into assistant-ui's textarea and keeping it in step with every edit; the
 * case this is for -- typing `@no` and wanting `notes.md` -- is at the end of
 * the line every time. A mention earlier in the sentence still works, it just
 * gets no suggestions while you go back and edit it.
 *
 * The Gateway resolves whatever is sent; this only helps type it.
 */
export interface Mention {
  /** What has been typed after the `@`, possibly empty. */
  query: string
  /** Where the `@` is, so the completion can replace from there. */
  at: number
}

export function trailingMention(text: string): Mention | null {
  const match = /(?:^|\s)@([^\s@]*)$/.exec(text ?? '')
  if (!match) return null
  return { query: match[1], at: text.length - match[1].length - 1 }
}

/** The composer text with the mention completed, ready for the next word. */
export function completeMention(text: string, mention: Mention, path: string): string {
  const quoted = /\s/.test(path) ? `"${path}"` : path
  return `${text.slice(0, mention.at)}@${quoted} `
}
