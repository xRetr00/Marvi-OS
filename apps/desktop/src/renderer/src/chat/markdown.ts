// Minimal, safe markdown parsing for agent replies.
//
// Marvi's answers are conversational, but they occasionally contain fenced
// code blocks and inline `code`. Rendering those as real blocks (rather than
// raw backticks) is the difference between a readable answer and noise. This
// is deliberately tiny: no HTML injection (everything renders as React text
// nodes), no external markdown dependency, and only the constructs the model
// actually emits — code fences and inline code — because full markdown clashes
// with the terminal UI contract.

export type Block =
  { kind: 'paragraph'; text: string } | { kind: 'code'; lang: string; text: string }

export type InlineNode = { type: 'text'; value: string } | { type: 'code'; value: string }

const FENCE_START = /^```([^\n]*)$/

/** Split text into paragraph and fenced-code blocks. Pure, no HTML. */
export function parseBlocks(content: string): Block[] {
  const lines = content.split('\n')
  const blocks: Block[] = []
  let paragraph: string[] = []
  let i = 0

  const flush = (): void => {
    const text = paragraph.join('\n')
    paragraph = []
    if (text.trim() !== '') blocks.push({ kind: 'paragraph', text })
  }

  while (i < lines.length) {
    const match = FENCE_START.exec(lines[i])
    if (match) {
      flush()
      const lang = (match[1] ?? '').trim()
      i += 1
      const code: string[] = []
      while (i < lines.length && !lines[i].startsWith('```')) {
        code.push(lines[i])
        i += 1
      }
      if (i < lines.length) i += 1 // closing fence
      blocks.push({ kind: 'code', lang, text: code.join('\n') })
    } else {
      paragraph.push(lines[i])
      i += 1
    }
  }
  flush()
  return blocks
}

/** Split a paragraph into text and inline-code spans. Pure, no HTML. */
export function parseInline(text: string): InlineNode[] {
  const nodes: InlineNode[] = []
  const re = /`([^`\n]+)`/g
  let last = 0
  let match: RegExpExecArray | null
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) nodes.push({ type: 'text', value: text.slice(last, match.index) })
    nodes.push({ type: 'code', value: match[1] })
    last = match.index + match[0].length
  }
  if (last < text.length) nodes.push({ type: 'text', value: text.slice(last) })
  return nodes
}
