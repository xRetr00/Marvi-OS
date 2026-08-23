import { metaValue, type ChatMessage } from './types'

function heading(message: ChatMessage): string {
  if (message.role === 'user') return 'You'
  if (message.role === 'assistant') return 'Marvi'
  if (message.role === 'tool') return `Tool · ${metaValue(message.meta, 'tool') || 'result'}`
  return 'Error'
}

export function transcriptMarkdown(messages: readonly ChatMessage[]): string {
  return messages
    .map((message) => `## ${heading(message)}\n\n${message.content.trim()}`)
    .join('\n\n---\n\n')
}

export function downloadTranscript(messages: readonly ChatMessage[]): void {
  const blob = new Blob([transcriptMarkdown(messages)], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `marvi-chat-${new Date().toISOString().slice(0, 10)}.md`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}
