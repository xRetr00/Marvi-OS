/**
 * A reply's parts, with the work gathered into one disclosure.
 *
 * `MessagePrimitive.GroupedParts` coalesces *adjacent* runs of parts that
 * `groupWork` marks as work, so a turn that thought, commented, searched and
 * read arrives as one "Marvi worked for Ns" block followed by its answer --
 * which is the order it happened in, and the order the Gateway now stores.
 *
 * Every leaf is rendered here rather than through the SDK's tool-UI registry:
 * `GroupedParts` only knows tools registered with `useAssistantToolUI`, and
 * Marvi's widget and question cards are plain components, so they are
 * dispatched by tool name below instead.
 */

import type { MessageState, ToolCallMessagePartProps } from '@assistant-ui/react'
import { MessagePrimitive } from '@assistant-ui/react'

import { GlyphSpinner } from '../../components/ui/glyph-spinner'
import { Markdown } from '../MarkdownView'
import { ASK_TOOL, WIDGET_TOOL } from '../runtime/convert'
import { ActivityLabel } from './ActivityLabel'
import { groupWork } from './group-work'
import { MESSAGE_PART_COMPONENTS } from './parts'
import { AskToolUI, WidgetToolUI } from './tool-uis'
import { toolSentence } from './tool-verbs'
import { CommentaryStep, ThoughtStep, ToolStep, WorkLog } from './WorkLog'

type Content = MessageState['content'][number]

/** What the header says while the work runs: the step happening right now. */
function currentActivity(part: Content | undefined): string {
  if (!part) return 'Marvi is working'
  if (part.type === 'reasoning') return 'Marvi is thinking'
  if (part.type === 'tool-call') return toolSentence(part.toolName, true)
  return 'Marvi is working'
}

export function AssistantParts({ message }: { message: MessageState }): React.JSX.Element {
  const custom = (message.metadata?.custom ?? {}) as { workedMs?: number }
  const startedAt = (message.createdAt ?? new Date()).getTime()
  const { Image, File } = MESSAGE_PART_COMPONENTS

  return (
    // `empty`: the trailing indicator only when nothing has arrived yet. Once a
    // work log exists its header already says what is happening, and a second
    // "Marvi is working" under it said the same thing twice.
    <MessagePrimitive.GroupedParts groupBy={groupWork} indicator="empty">
      {({ part, children }) => {
        switch (part.type) {
          case 'group-work': {
            const indices = part.indices
            const steps = indices.filter((index) => message.content[index]?.type === 'tool-call')
            return (
              <WorkLog
                activity={currentActivity(message.content[indices[indices.length - 1]])}
                running={part.status.type === 'running'}
                startedAt={startedAt}
                steps={steps.length}
                workedMs={custom.workedMs ?? 0}
              >
                {children}
              </WorkLog>
            )
          }

          case 'reasoning':
            return part.text.trim() ? (
              <ThoughtStep live={part.status?.type === 'running'} text={part.text} />
            ) : null

          case 'data': {
            const text = (part.data as { text?: string } | undefined)?.text ?? ''
            return part.name === 'commentary' && text.trim() ? <CommentaryStep text={text} /> : null
          }

          case 'tool-call': {
            const props = part as unknown as ToolCallMessagePartProps
            if (part.toolName === WIDGET_TOOL) return <WidgetToolUI {...props} />
            if (part.toolName === ASK_TOOL) return <AskToolUI {...props} />
            const status =
              part.status.type === 'running' ? 'running' : part.isError ? 'failed' : 'complete'
            return (
              <ToolStep
                args={(part.args ?? {}) as Record<string, unknown>}
                name={part.toolName}
                result={typeof part.result === 'string' ? part.result : ''}
                status={status}
              />
            )
          }

          case 'text':
            return part.text.trim() ? (
              <div className="chat-body chat-assistant-prose">
                <Markdown content={part.text} />
              </div>
            ) : null

          case 'image':
            return <Image {...(part as Parameters<typeof Image>[0])} />

          case 'file':
            return <File {...(part as Parameters<typeof File>[0])} />

          case 'indicator':
            // Only ever emitted while the message is running, so it cannot be
            // left behind on a finished reply the way the old empty slot was.
            return (
              <div className="chat-scaffold chat-stream-activity" data-conversation-scaffold="">
                <GlyphSpinner ariaLabel="Marvi is working" className="chat-working-spinner" />
                <ActivityLabel live text="Marvi is working" />
              </div>
            )

          default:
            // Sources render as one grouped card through the sources widget;
            // anything else unknown renders nothing rather than a raw part.
            return null
        }
      }}
    </MessagePrimitive.GroupedParts>
  )
}
