/**
 * Slash commands: the few things you want to *do* to a conversation rather
 * than say into it.
 *
 * The bar for one being here is that it does something you cannot already get
 * by typing English. "Summarise this" is a message; Marvi is good at it and it
 * costs a turn to ask. Folding the part of the conversation that has scrolled
 * out of the window is not a message -- there is no sentence that does it,
 * because it happens to the transcript rather than in it. That is the whole
 * test, and it is why this list is short.
 */

/** One command, as the popover shows it and as the composer runs it. */
export interface SlashCommand {
  id: string
  /** What the popover says under the name. Also matched when filtering. */
  description: string
  /** What the rest of the line means. Empty when the command takes none. */
  argument?: string
}

export const SLASH_COMMANDS: readonly SlashCommand[] = [
  {
    id: 'compress',
    description:
      'Fold what has scrolled out of this conversation into its running summary, now rather than after the next turn.'
  },
  {
    id: 'goal',
    description: 'Put this on the jobs board as a card, instead of losing it in the scroll.',
    argument: 'what the job is'
  },
  {
    id: 'new',
    description: 'Start a fresh conversation. This one is kept.'
  }
]

/**
 * Where the `/` trigger starts and ends in a draft, for assistant-ui.
 *
 * Replaces the default detection, which stops at the first space -- correct
 * for `@file`, wrong here. `/goal buy milk before six` is one command with an
 * argument, and a popover that vanishes at the space leaves no way to run it.
 *
 * Two things follow from that. The slash has to be the first character, so a
 * slash inside a sentence ("and/or", a path, a date) is never a command. And
 * the query is the first word only, so the list narrows on the command name
 * while the rest of the line is left alone as its argument.
 */
export function slashTrigger(
  text: string,
  char: string,
  cursor: number
): { query: string; offset: number; endOffset: number } | null {
  if (char !== '/' || !text.startsWith('/') || cursor < 1) return null
  return { query: text.slice(1).split(/\s/)[0], offset: 0, endOffset: text.length }
}

/**
 * The argument for a command, given the draft it was run from.
 *
 * `/goal buy milk` run as `goal` is "buy milk". Running `/goal` from a draft
 * that says something else entirely -- which the popover allows, since it
 * matches on the description too -- gives nothing rather than nonsense.
 */
export function commandArgument(draft: string, id: string): string {
  const match = new RegExp(`^/${id}(?:\\s+([\\s\\S]*))?$`, 'i').exec(draft.trim())
  return (match?.[1] ?? '').trim()
}
