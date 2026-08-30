import { AbstractIcon } from '../../components/abstract-icon'
import { GlyphSpinner } from '../../components/ui/glyph-spinner'
import { UiTooltip } from '../../components/ui/tooltip'
import { Markdown } from '../MarkdownView'
import { formatTime } from '../time'
import { metaValue, type ChatMessage } from '../types'
import { CopyMessageAction } from './MessageAction'
import { ActivityTimer } from './ActivityTimer'
import { ReasoningDisclosure, StreamActivity } from './ReasoningDisclosure'
import { WidgetStack } from './WidgetStack'

export function AgentMessage({
  message,
  readAloud,
  onRegenerate
}: {
  message: ChatMessage
  readAloud?: { available: boolean; reading: boolean; toggle: () => void }
  onRegenerate?: (id: number) => void
}): React.JSX.Element {
  const reasoning = metaValue(message.meta, 'reasoning')
  const streaming = Boolean(message.meta?.streaming)
  const tool = metaValue(message.meta, 'tool')

  return (
    <article
      aria-busy={streaming ? 'true' : undefined}
      aria-label="Marvi response"
      className="chat-turn chat-assistant"
    >
      <span className="sr-only">MARVI</span>
      {reasoning ? (
        <ReasoningDisclosure reasoning={reasoning} startedAt={message.at} streaming={streaming} />
      ) : null}
      {tool ? (
        <div className="chat-scaffold chat-inline-tool" data-conversation-scaffold="">
          {streaming ? (
            <GlyphSpinner
              ariaLabel={`Marvi is using ${toolLabel(tool)}`}
              className="chat-working-spinner"
              spinner="braille"
            />
          ) : (
            <span aria-hidden="true" className="chat-tool-dot" />
          )}
          <span className={streaming ? 'chat-scaffold-label is-live' : 'chat-scaffold-label'}>
            {streaming ? 'Using' : 'Used'} {toolLabel(tool)}
          </span>
          {streaming ? <ActivityTimer active startedAt={message.at} /> : null}
        </div>
      ) : null}
      {message.content.trim() ? (
        <div className="chat-body chat-assistant-prose">
          <Markdown content={message.content} />
        </div>
      ) : null}
      <WidgetStack parts={message.parts} />
      {streaming && !tool && message.content.trim() ? (
        <StreamActivity startedAt={message.at} />
      ) : null}
      <div className="chat-turn-foot">
        <div className="chat-turn-actions">
          <span className="chat-message-age">{formatTime(message.at)}</span>
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

function toolLabel(tool: string): string {
  return tool.replaceAll(/[_-]+/g, ' ').replace(/^\w/, (letter) => letter.toUpperCase())
}
