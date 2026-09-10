/**
 * Marvi's stored chat shape, in the shape assistant-ui renders.
 *
 * Kept free of React and of every `window.marvi` call so it can be tested as
 * what it is: a total function from one wire format to another. This is the
 * seam the whole refactor rests on -- if a message renders wrong, it renders
 * wrong here, and a pure test says so in a line.
 *
 * ## Widgets ride in as tool calls
 *
 * `ThreadMessageLike.content` is a closed union and `widget` is not in it, so
 * a widget could only have arrived as a bolted-on custom part. It did not need
 * to: a widget is already `{kind, title, status, data}`, which is the same
 * information as `{toolName, status, result}`. Mapping it onto a tool-call part
 * costs nothing, needs no Gateway change, and means the widget renderers are
 * ordinary generative UI rather than a special case beside it.
 *
 * Widgets stay validated data the Gateway produced. Nothing here reads a widget
 * as an instruction, and the renderers pick components by `kind` from a fixed
 * table -- a widget can never name the component that draws it.
 */

import type { ChatAttachment, ChatPart, ChatWidgetPart } from '../../../../shared/runtime'
import type { ChatMessage } from '../types'
import { metaValue } from '../types'

/** The tool name every Marvi widget arrives under. */
export const WIDGET_TOOL = 'marvi_widget'

/** The tool name an inline `clarify`/`ask_secret` card arrives under. */
export const ASK_TOOL = 'marvi_ask'

/** Loose local mirrors of assistant-ui's part union.
 *
 * Written out rather than imported so this module stays testable without
 * pulling the SDK (and a DOM) into a unit test. The shapes are checked against
 * the real ones where the runtime consumes them, which is the only place the
 * mismatch could actually bite.
 */
/** What a tool-call part may carry. assistant-ui requires JSON, not `unknown`. */
export type JsonValue =
  string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }
export type JsonObject = { [key: string]: JsonValue }

export type UiPart =
  | { type: 'text'; text: string }
  | { type: 'reasoning'; text: string }
  | { type: 'source'; sourceType: 'url'; id: string; url: string; title?: string }
  | { type: 'image'; image: string; filename?: string }
  | { type: 'file'; filename?: string; data: string; mimeType: string }
  | {
      type: 'tool-call'
      toolCallId: string
      toolName: string
      args?: JsonObject
      result?: JsonValue
      isError?: boolean
    }

export interface UiMessage {
  role: 'user' | 'assistant'
  content: UiPart[]
  id: string
  createdAt: Date
  status?:
    | { type: 'running' }
    | { type: 'complete'; reason: 'stop' }
    | {
        type: 'incomplete'
        reason: 'error'
        error: string
      }
  attachments?: {
    id: string
    type: 'document'
    name: string
    contentType: string
    status: { type: 'complete' }
    content: { type: 'text'; text: string }[]
  }[]
  metadata?: { custom: JsonObject }
}

/** Roles Marvi stores that never render as their own bubble.
 *
 * `tool` rows exist so the model can replay what a tool returned; the user
 * already saw the result as a widget or a card on the message that called it.
 * Rendering them too would show every tool twice.
 */
const HIDDEN_ROLES: ReadonlySet<string> = new Set(['tool'])

export function isRenderable(message: ChatMessage): boolean {
  return !HIDDEN_ROLES.has(message.role)
}

/** A stable id for a part that has none of its own.
 *
 * Index-based, because the alternative -- a fresh id per render -- remounts
 * every card on every streamed delta, which drops focus out of an open
 * `clarify` box while somebody is typing into it.
 */
function partId(message: ChatMessage, index: number): string {
  return `${message.id}:${index}`
}

export function widgetPart(widget: ChatWidgetPart, fallbackId: string): UiPart {
  return {
    type: 'tool-call',
    toolCallId: widget.id || fallbackId,
    toolName: WIDGET_TOOL,
    args: { kind: widget.kind, title: widget.title },
    result: widget as unknown as JsonValue,
    isError: widget.status === 'error'
  }
}

function convertPart(part: ChatPart, message: ChatMessage, index: number): UiPart | null {
  switch (part.type) {
    case 'text':
      return part.text ? { type: 'text', text: part.text } : null
    case 'source':
      return {
        type: 'source',
        sourceType: 'url',
        id: partId(message, index),
        url: part.url,
        title: part.title || part.url
      }
    case 'image':
      // An attachment-backed image is fetched by id through the preload
      // bridge, so only a part that already carries a url can render here.
      return part.url ? { type: 'image', image: part.url, filename: part.alt } : null
    case 'file':
      return part.attachment_id
        ? {
            type: 'file',
            filename: part.name,
            data: part.attachment_id,
            mimeType: part.media_type || 'application/octet-stream'
          }
        : null
    case 'tool':
      return {
        type: 'tool-call',
        toolCallId: partId(message, index),
        toolName: part.name,
        args: {},
        result: part.content ?? '',
        isError: part.status === 'failed'
      }
    case 'ask':
      return {
        type: 'tool-call',
        toolCallId: part.id,
        toolName: ASK_TOOL,
        args: {
          kind: part.kind,
          question: part.question ?? '',
          choices: part.choices ?? [],
          multi_select: Boolean(part.multi_select),
          name: part.name ?? '',
          why: part.why ?? ''
        },
        // A card with no result is a card still being waited on, which is
        // exactly how a generative tool UI reads "running".
        ...(part.answered ? { result: { answered: true } } : {})
      }
    case 'widget':
      return widgetPart(part, partId(message, index))
    case 'attachment':
      // Carried on the message, not in its content. assistant-ui renders
      // attachments in their own row above the text.
      return null
    default:
      return null
  }
}

function convertAttachment(
  attachment: ChatAttachment
): NonNullable<UiMessage['attachments']>[number] {
  return {
    id: attachment.id,
    type: 'document',
    name: attachment.name,
    contentType: attachment.media_type || 'application/octet-stream',
    status: { type: 'complete' },
    content: []
  }
}

function statusFor(message: ChatMessage): UiMessage['status'] {
  if (message.role === 'error') {
    return { type: 'incomplete', reason: 'error', error: message.content }
  }
  if (message.meta.streaming) return { type: 'running' }
  return { type: 'complete', reason: 'stop' }
}

/** Part types assistant-ui accepts on a *user* message.
 *
 * The union is enforced at runtime, not just in types: `fromThreadMessageLike`
 * throws on anything else and React 19 then unmounts the whole tree, so a
 * stray `source` part on a user row blanks the window. Reasoning, sources and
 * tool calls belong to the assistant by construction anyway.
 */
const USER_PART_TYPES: ReadonlySet<string> = new Set(['text', 'image', 'file'])

/**
 * One stored message as assistant-ui renders it.
 *
 * An `error` row becomes an assistant message carrying an error status rather
 * than a fourth role: assistant-ui has three, and a bubble that renders as an
 * error is what an error row was always trying to be.
 *
 * The role split below is not cosmetic. `fromThreadMessageLike` rejects a
 * `status` on anything but an assistant message, `attachments` on anything but
 * a user message, and unknown part types on either -- each with a throw, which
 * with no error boundary meant a black window instead of a bad bubble.
 */
export function convertMessage(message: ChatMessage): UiMessage {
  const isUser = message.role === 'user'
  const content: UiPart[] = []

  if (!isUser) {
    const reasoning = metaValue(message.meta, 'reasoning')
    // Ahead of the answer, because that is the order it was produced in and
    // the order the disclosure reads in.
    if (reasoning) content.push({ type: 'reasoning', text: reasoning })
  }

  message.parts.forEach((part, index) => {
    const converted = convertPart(part, message, index)
    if (!converted) return
    if (isUser && !USER_PART_TYPES.has(converted.type)) return
    content.push(converted)
  })

  // A message whose parts produced nothing renderable still has to occupy a
  // row -- an assistant message mid-stream has no parts yet, and dropping it
  // would make the thinking indicator flicker in and out.
  if (!content.length && message.content) content.push({ type: 'text', text: message.content })

  const attachments = isUser ? message.attachments.map(convertAttachment) : []

  return {
    role: isUser ? 'user' : 'assistant',
    content,
    id: String(message.id),
    createdAt: new Date(message.at),
    ...(isUser ? {} : { status: statusFor(message) }),
    ...(attachments.length ? { attachments } : {}),
    metadata: {
      custom: {
        marviRole: message.role,
        threadId: message.threadId,
        provider: metaValue(message.meta, 'provider'),
        model: metaValue(message.meta, 'model'),
        tool: metaValue(message.meta, 'tool')
      }
    }
  }
}

export function convertMessages(messages: readonly ChatMessage[]): UiMessage[] {
  return messages.filter(isRenderable).map(convertMessage)
}
