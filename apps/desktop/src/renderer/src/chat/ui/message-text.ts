import type { MessageState } from '@assistant-ui/react'

/**
 * The plain text of a message, for copying and for reading aloud.
 *
 * Its own module so `Messages.tsx` exports only components. Tool calls,
 * reasoning and widgets are deliberately excluded: read-aloud should speak the
 * answer, not narrate the machinery that produced it.
 */
export function messageText(message: MessageState): string {
  return message.content
    .filter((part): part is { type: 'text'; text: string } => part.type === 'text')
    .map((part) => part.text)
    .join('\n')
}
