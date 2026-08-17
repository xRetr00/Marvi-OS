import type { ReactNode } from 'react'

import { parseBlocks, parseInline } from './markdown'

/** Render agent content as code blocks plus paragraphs with inline code. */
export function Markdown({ content }: { content: string }): ReactNode {
  const blocks = parseBlocks(content)
  if (blocks.length === 0) return null
  return (
    <>
      {blocks.map((block, i) =>
        block.kind === 'code' ? (
          <pre className="chat-code" data-lang={block.lang || undefined} key={i}>
            <code>{block.text}</code>
          </pre>
        ) : (
          <p className="chat-para" key={i}>
            {renderInline(block.text, i)}
          </p>
        )
      )}
    </>
  )
}

function renderInline(text: string, blockIndex: number): ReactNode[] {
  const nodes = parseInline(text)
  if (nodes.length === 0) return [text]
  return nodes.map((node, i) =>
    node.type === 'code' ? (
      <code className="chat-inline-code" key={`${blockIndex}-${i}`}>
        {node.value}
      </code>
    ) : (
      <span key={`${blockIndex}-${i}`}>{node.value}</span>
    )
  )
}
