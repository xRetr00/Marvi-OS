/**
 * Which component draws which kind of message part.
 *
 * One table, passed to every `MessagePrimitive.Parts`. Text goes through the
 * Markdown renderer that was already here -- with GFM, math and the safe-link
 * rules -- so switching to the SDK changed the plumbing and not a single
 * rendered character.
 */

import { useState } from 'react'
import { ChevronDown } from 'lucide-react'

import type {
  EmptyMessagePartComponent,
  FileMessagePartProps,
  ImageMessagePartProps,
  ReasoningMessagePartProps,
  TextMessagePartProps
} from '@assistant-ui/react'

import { GlyphSpinner } from '../../components/ui/glyph-spinner'
import { ActivityLabel } from './ActivityLabel'
import { Markdown } from '../MarkdownView'
import { AskToolUI, ToolActivity, WidgetToolUI } from './tool-uis'
import { ASK_TOOL, WIDGET_TOOL } from '../runtime/convert'

/** Read-aloud, threaded down from the page that owns the hook. */
export interface ReadAloud {
  available: boolean
  readingId: number | null
  toggle: (id: number, content: string) => void
}

const Text = ({ text }: TextMessagePartProps): React.JSX.Element | null =>
  text.trim() ? (
    <div className="chat-body chat-assistant-prose">
      <Markdown content={text} />
    </div>
  ) : null

const Reasoning = ({ text, status }: ReasoningMessagePartProps): React.JSX.Element | null => {
  const streaming = status?.type === 'running'
  // Open while it is being written, and then whatever you last chose.
  //
  // This used to be `open={streaming}`, which React re-applies on every
  // render: the disclosure slammed shut the instant the turn finished, and
  // clicking it open again did nothing because the next delta closed it. The
  // null means "nobody has decided yet", which is what lets streaming decide.
  const [chosen, setChosen] = useState<boolean | null>(null)
  const open = chosen ?? streaming
  if (!text.trim()) return null
  return (
    <section
      className="chat-scaffold chat-reasoning"
      data-conversation-scaffold=""
      data-state={streaming ? 'streaming' : 'complete'}
    >
      <button
        aria-expanded={open}
        className="chat-disclosure-row"
        onClick={() => setChosen(!open)}
        type="button"
      >
        {streaming ? (
          <GlyphSpinner ariaLabel="Marvi is thinking" className="chat-working-spinner" />
        ) : null}
        <ActivityLabel live={streaming} text={streaming ? 'Marvi is thinking' : 'Marvi thoughts'} />
        <ChevronDown
          aria-hidden="true"
          className={open ? 'chat-disclosure-caret is-open' : 'chat-disclosure-caret'}
          size={13}
          strokeWidth={1.6}
        />
      </button>
      {open ? (
        <div className={streaming ? 'chat-reasoning-body is-live' : 'chat-reasoning-body'}>
          <Markdown content={text} />
        </div>
      ) : null}
    </section>
  )
}

const Source = (): null =>
  // Sources render as one grouped card via the `sources` widget rather than as
  // a part each. A row of bare links under a paragraph is what the widget was
  // built to replace.
  null

const Image = ({ image, filename }: ImageMessagePartProps): React.JSX.Element => (
  <img alt={filename || ''} className="chat-inline-image" src={image} />
)

const File = ({ filename, mimeType }: FileMessagePartProps): React.JSX.Element => (
  <div className="chat-inline-file">
    <span className="chat-inline-file-name">{filename || 'Attachment'}</span>
    <span className="chat-inline-file-type">{mimeType}</span>
  </div>
)

/**
 * Shown while an assistant message exists but has produced nothing yet.
 *
 * It checks its own status, and that check is the whole point. The SDK renders
 * this slot whenever a message *ends* on something that is not text or
 * reasoning -- a reply that finished on a widget or a tool card qualifies --
 * so a turn that ended perfectly well sat there saying "Marvi is working"
 * forever, including after the next turn had started.
 */
const Empty: EmptyMessagePartComponent = ({ status }) => {
  if (status?.type !== 'running') return null
  return (
    <div className="chat-scaffold chat-stream-activity" data-conversation-scaffold="">
      <GlyphSpinner ariaLabel="Marvi is working" className="chat-working-spinner" />
      <ActivityLabel live text="Marvi is working" />
    </div>
  )
}

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
