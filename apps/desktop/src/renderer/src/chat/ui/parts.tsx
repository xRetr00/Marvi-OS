/**
 * Which component draws which kind of message part.
 *
 * One table, passed to every `MessagePrimitive.Parts`. Text goes through the
 * Markdown renderer that was already here -- with GFM, math and the safe-link
 * rules -- so switching to the SDK changed the plumbing and not a single
 * rendered character.
 */

import type {
  EmptyMessagePartComponent,
  FileMessagePartComponent,
  ImageMessagePartComponent,
  ReasoningMessagePartComponent,
  SourceMessagePartComponent,
  TextMessagePartComponent
} from '@assistant-ui/react'

import { GlyphSpinner } from '../../components/ui/glyph-spinner'
import { Markdown } from '../MarkdownView'
import { AskToolUI, ToolActivity, WidgetToolUI } from './tool-uis'
import { ASK_TOOL, WIDGET_TOOL } from '../runtime/convert'

/** Read-aloud, threaded down from the page that owns the hook. */
export interface ReadAloud {
  available: boolean
  readingId: number | null
  toggle: (id: number, content: string) => void
}

const Text: TextMessagePartComponent = ({ text }) =>
  text.trim() ? (
    <div className="chat-body chat-assistant-prose">
      <Markdown content={text} />
    </div>
  ) : null

const Reasoning: ReasoningMessagePartComponent = ({ text, status }) => {
  // The disclosure component owns its own open/closed state, and remounting it
  // would slam it shut on every delta -- so reasoning renders through a plain
  // details element here and the streaming state rides on a data attribute.
  const streaming = status?.type === 'running'
  if (!text.trim()) return null
  return (
    <details
      className="chat-scaffold chat-reasoning"
      data-conversation-scaffold=""
      data-state={streaming ? 'streaming' : 'complete'}
      open={streaming}
    >
      <summary className="chat-disclosure-row">
        {streaming ? (
          <GlyphSpinner
            ariaLabel="Marvi is thinking"
            className="chat-working-spinner"
            spinner="braille"
          />
        ) : null}
        <span className={streaming ? 'chat-scaffold-label is-live' : 'chat-scaffold-label'}>
          {streaming ? 'Marvi is thinking' : 'Marvi thought'}
        </span>
      </summary>
      <div className={streaming ? 'chat-reasoning-body is-live' : 'chat-reasoning-body'}>
        <Markdown content={text} />
      </div>
    </details>
  )
}

const Source: SourceMessagePartComponent = () =>
  // Sources render as one grouped card via the `sources` widget rather than as
  // a part each. A row of bare links under a paragraph is what the widget was
  // built to replace.
  null

const Image: ImageMessagePartComponent = ({ image, filename }) => (
  <img alt={filename || ''} className="chat-inline-image" src={image} />
)

const File: FileMessagePartComponent = ({ filename, mimeType }) => (
  <div className="chat-inline-file">
    <span className="chat-inline-file-name">{filename || 'Attachment'}</span>
    <span className="chat-inline-file-type">{mimeType}</span>
  </div>
)

/** Shown while an assistant message exists but has produced nothing yet. */
const Empty: EmptyMessagePartComponent = () => (
  <div className="chat-scaffold chat-stream-activity" data-conversation-scaffold="">
    <GlyphSpinner
      ariaLabel="Marvi is working"
      className="chat-working-spinner"
      spinner="braille"
    />
    <span className="chat-scaffold-label is-live">Marvi is working</span>
  </div>
)

export const MESSAGE_PART_COMPONENTS = {
  Text,
  Reasoning,
  Source,
  Image,
  File,
  Empty,
  tools: {
    by_name: {
      [WIDGET_TOOL]: WidgetToolUI,
      [ASK_TOOL]: AskToolUI
    },
    // Every other tool gets the one-line footnote. A tool without a designed
    // card should not invent one.
    Fallback: ToolActivity
  }
} as const
