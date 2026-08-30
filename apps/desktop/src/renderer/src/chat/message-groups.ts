import type { ChatMessage } from './types'

export type MessageListItem =
  { kind: 'message'; message: ChatMessage } | { kind: 'tools'; messages: ChatMessage[] }

export function groupToolMessages(messages: ChatMessage[]): MessageListItem[] {
  const items: MessageListItem[] = []
  for (const message of messages) {
    const last = items.at(-1)
    if (message.role === 'tool') {
      if (last?.kind === 'tools') last.messages.push(message)
      else items.push({ kind: 'tools', messages: [message] })
    } else items.push({ kind: 'message', message })
  }
  return items
}
