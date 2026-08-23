import { toString } from 'mdast-util-to-string'
import remarkGfm from 'remark-gfm'
import remarkParse from 'remark-parse'
import { unified } from 'unified'

const MAX_SPEECH_CHARACTERS = 12_000
const MAX_UTTERANCE_CHARACTERS = 500
const TRUNCATION_NOTICE = 'Response truncated for read aloud.'

type Node = {
  type: string
  value?: string
  url?: string
  alt?: string | null
  checked?: boolean | null
  ordered?: boolean
  children?: Node[]
}

export function markdownToSpeechChunks(markdown: string): string[] {
  const tree = unified().use(remarkParse).use(remarkGfm).parse(markdown) as Node
  const sections = sectionsFor(tree).map(normalize).filter(Boolean)
  const combined = sections.join('\n\n')
  const truncated = combined.length > MAX_SPEECH_CHARACTERS
  const limit = truncated
    ? MAX_SPEECH_CHARACTERS - TRUNCATION_NOTICE.length - 2
    : MAX_SPEECH_CHARACTERS
  const chunks = splitSpeech(combined.slice(0, safeSplit(combined, limit)))
  if (truncated) chunks.push(TRUNCATION_NOTICE)
  return chunks
}

function sectionsFor(node: Node): string[] {
  switch (node.type) {
    case 'root':
      return (node.children ?? []).flatMap(sectionsFor)
    case 'code':
      return ['Code block omitted.']
    case 'thematicBreak':
    case 'html':
    case 'definition':
      return []
    case 'table':
      return tableSections(node)
    case 'list':
      return (node.children ?? []).flatMap((child, index) => {
        if (child.checked !== null && child.checked !== undefined) return sectionsFor(child)
        const value = inlineText(child)
        return value ? [`${node.ordered ? `${index + 1}.` : 'Item:'} ${value}`] : []
      })
    case 'listItem': {
      const value = inlineText(node)
      if (node.checked === true) return [`Completed: ${value}`]
      if (node.checked === false) return [`Not completed: ${value}`]
      return value ? [value] : []
    }
    default: {
      const value = inlineText(node)
      return value ? [value] : []
    }
  }
}

function tableSections(node: Node): string[] {
  const rows = node.children ?? []
  if (rows.length === 0) return []
  const headers = (rows[0].children ?? []).map(inlineText)
  const sections = headers.some(Boolean)
    ? [`Table columns: ${headers.filter(Boolean).join(', ')}.`]
    : []
  for (const [index, row] of rows.slice(1).entries()) {
    const cells = (row.children ?? [])
      .map((cell, cellIndex) => {
        const value = inlineText(cell)
        return value ? `${headers[cellIndex] ? `${headers[cellIndex]}: ` : ''}${value}` : ''
      })
      .filter(Boolean)
    if (cells.length) sections.push(`Row ${index + 1}. ${cells.join('; ')}.`)
  }
  return sections
}

function inlineText(node: Node): string {
  if (node.type === 'link') {
    const label = normalize(toString(node as never))
    return label && label !== node.url ? label : 'link'
  }
  if (node.type === 'image') return normalize(node.alt || 'Image')
  if (node.type === 'inlineCode') return normalize(node.value || '')
  if (node.type === 'text') return redactUris(node.value || '')
  if (node.type === 'break') return ' '
  return redactUris((node.children ?? []).map(inlineText).join(' '))
}

function redactUris(text: string): string {
  return text.replace(/\b[a-z][a-z\d+.-]*:\/\/[^\s<>{}"'`]+/gi, 'link')
}

function splitSpeech(text: string): string[] {
  const chunks: string[] = []
  let remaining = text.trim()
  while (remaining.length > MAX_UTTERANCE_CHARACTERS) {
    const candidate = remaining.slice(0, MAX_UTTERANCE_CHARACTERS + 1)
    const sentence = Math.max(
      candidate.lastIndexOf('. '),
      candidate.lastIndexOf('? '),
      candidate.lastIndexOf('! ')
    )
    const whitespace = candidate.lastIndexOf(' ')
    const cut =
      sentence > MAX_UTTERANCE_CHARACTERS / 2
        ? sentence + 1
        : whitespace > 0
          ? whitespace
          : MAX_UTTERANCE_CHARACTERS
    const at = safeSplit(remaining, cut)
    chunks.push(remaining.slice(0, at).trim())
    remaining = remaining.slice(at).trimStart()
  }
  if (remaining) chunks.push(remaining)
  return chunks
}

function safeSplit(text: string, requested: number): number {
  const index = Math.max(0, Math.min(requested, text.length))
  const before = text.charCodeAt(index - 1)
  const after = text.charCodeAt(index)
  return before >= 0xd800 && before <= 0xdbff && after >= 0xdc00 && after <= 0xdfff
    ? index - 1
    : index
}

function normalize(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}
