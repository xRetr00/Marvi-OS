import { useState } from 'react'

import { AbstractIcon } from '../../components/abstract-icon'
import { UiTooltip } from '../../components/ui/tooltip'
import { Markdown } from '../MarkdownView'
import { formatTime } from '../time'
import { metaValue, type ChatMessage } from '../types'
import { CopyMessageAction } from './MessageAction'

export function AgentMessage({
  message,
  readAloud,
  onRegenerate
}: {
  message: ChatMessage
  readAloud?: { available: boolean; reading: boolean; toggle: () => void }
  onRegenerate?: (id: number) => void
}): React.JSX.Element {
  const provider = metaValue(message.meta, 'provider')
  const tokens = metaValue(message.meta, 'tokens')
  const reasoning = metaValue(message.meta, 'reasoning')
  const streaming = Boolean(message.meta?.streaming)
  const [showReasoning, setShowReasoning] = useState(false)
  const sources = message.parts.filter(
    (part): part is Extract<(typeof message.parts)[number], { type: 'source' }> =>
      part.type === 'source'
  )

  return (
    <article className="chat-turn chat-assistant">
      <div className="chat-turn-head">
        <span className="chat-role">MARVI</span>
        <span className="chat-time">{formatTime(message.at)}</span>
      </div>
      {reasoning ? (
        <div className="chat-reasoning">
          {/* Collapsed by default and never part of the answer. It is the
              model's working, not something Marvi said — and on a thinking
              model it is most of the bill, which is worth being able to see. */}
          <button
            className="chat-reasoning-toggle"
            onClick={() => setShowReasoning((open) => !open)}
            type="button"
          >
            {showReasoning ? '▾' : '▸'} Thinking
          </button>
          {showReasoning ? <pre className="chat-reasoning-body">{reasoning}</pre> : null}
        </div>
      ) : null}
      <div className="chat-body">
        <Markdown content={message.content} />
        {streaming ? (
          // Only while tokens are still arriving. A cursor on a finished
          // message says the reply is unfinished when it is not.
          <span aria-hidden="true" className="chat-cursor" />
        ) : null}
      </div>
      {sources.length ? (
        <section className="chat-sources" aria-label="Sources">
          <div className="chat-sources-title">SOURCES · {sources.length}</div>
          <div className="chat-source-list">
            {sources.map((source, index) => (
              <a href={source.url} key={source.url} rel="noreferrer noopener" target="_blank">
                <span>{String(index + 1).padStart(2, '0')}</span>
                <strong>{source.title}</strong>
                <small>{sourceHost(source.url)}</small>
              </a>
            ))}
          </div>
        </section>
      ) : null}
      <div className="chat-turn-foot">
        <span className="chat-meta">
          {provider}
          {provider && tokens ? ' · ' : ''}
          {tokens ? `${tokens} tok` : ''}
        </span>
        <div className="chat-turn-actions">
          {readAloud?.available && !streaming ? (
            <UiTooltip label={readAloud.reading ? 'Stop reading' : 'Read aloud'}>
              <button
                aria-label={readAloud.reading ? 'Stop reading' : 'Read aloud'}
                aria-pressed={readAloud.reading}
                onClick={readAloud.toggle}
                type="button"
              >
                <AbstractIcon name={readAloud.reading ? 'stop' : 'speaker'} size={14} />
              </button>
            </UiTooltip>
          ) : null}
          {onRegenerate && message.id > 0 && !streaming ? (
            <UiTooltip label="Regenerate on a new branch">
              <button
                aria-label="Regenerate response"
                onClick={() => onRegenerate(message.id)}
                type="button"
              >
                <AbstractIcon name="regenerate" size={14} />
              </button>
            </UiTooltip>
          ) : null}
          <CopyMessageAction content={message.content} label="Copy response" />
        </div>
      </div>
    </article>
  )
}

function sourceHost(url: string): string {
  try {
    return new URL(url).hostname
  } catch {
    return 'source'
  }
}
