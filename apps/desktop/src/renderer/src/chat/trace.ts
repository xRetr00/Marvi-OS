/**
 * A streamed turn, folded into parts in the order it happened.
 *
 * The stream used to be folded into two strings -- every reasoning chunk into
 * one, every text chunk into another -- which is why the work was invisible:
 * a thought, a line of commentary, a web search, another thought and the
 * answer arrived as "thinking" plus "answer", with the search nowhere. Keeping
 * each event as its own part, in sequence, is what lets the window show the
 * trace as it runs and what makes the live view match the stored one.
 *
 * Pure, so the whole protocol can be tested as a list of events in and a list
 * of parts out.
 */

import type { ChatAskPart, ChatPart, ChatToolPart, ChatWidgetPart } from '../../../shared/runtime'

type Event = Record<string, unknown>

function last(parts: readonly ChatPart[]): ChatPart | undefined {
  return parts[parts.length - 1]
}

/** Append to the trailing part of `type`, or start a new one. */
function extend(parts: ChatPart[], type: 'text' | 'reasoning', chunk: string): ChatPart[] {
  const tail = last(parts)
  if (tail && tail.type === type) {
    return [...parts.slice(0, -1), { ...tail, text: tail.text + chunk }]
  }
  return [...parts, { type, text: chunk }]
}

function toolCall(value: Event): ChatToolPart {
  return {
    type: 'tool',
    id: String(value.id ?? ''),
    name: String(value.name ?? ''),
    arguments:
      value.arguments && typeof value.arguments === 'object'
        ? (value.arguments as Record<string, unknown>)
        : {},
    status: 'running'
  }
}

function askPart(ask: Event): ChatAskPart {
  return {
    type: 'ask',
    id: String(ask.id ?? ''),
    kind: ask.kind === 'secret' ? 'secret' : 'clarify',
    question: typeof ask.question === 'string' ? ask.question : '',
    choices: Array.isArray(ask.choices) ? (ask.choices as string[]) : [],
    multi_select: Boolean(ask.multi_select),
    name: typeof ask.name === 'string' ? ask.name : '',
    why: typeof ask.why === 'string' ? ask.why : ''
  }
}

/**
 * One stream event applied to the parts so far.
 *
 * Events this does not recognise leave the parts untouched, so a Gateway that
 * sends something new never corrupts what is already on screen.
 */
export function foldEvent(parts: ChatPart[], event: Event): ChatPart[] {
  if (typeof event.reasoning === 'string') return extend(parts, 'reasoning', event.reasoning)
  if (typeof event.delta === 'string') return extend(parts, 'text', event.delta)

  if (event.tool_call && typeof event.tool_call === 'object') {
    // Text written before a tool call was commentary, not the answer. It
    // already streamed in as `text`; now that a call has followed it, it is
    // reclassified in place -- which is exactly what the Gateway stores.
    const tail = last(parts)
    const settled =
      tail && tail.type === 'text'
        ? tail.text.trim()
          ? [...parts.slice(0, -1), { type: 'commentary' as const, text: tail.text.trim() }]
          : parts.slice(0, -1)
        : parts
    return [...settled, toolCall(event.tool_call as Event)]
  }

  if (event.tool_result && typeof event.tool_result === 'object') {
    const result = event.tool_result as Event
    const id = String(result.id ?? '')
    return parts.map((part) =>
      part.type === 'tool' && part.id === id
        ? {
            ...part,
            content: typeof result.content === 'string' ? result.content : '',
            status: result.status === 'failed' ? 'failed' : 'complete'
          }
        : part
    )
  }

  if (event.widget && typeof event.widget === 'object') {
    return [...parts, event.widget as ChatWidgetPart]
  }

  if (event.ask && typeof event.ask === 'object') {
    return [...parts, askPart(event.ask as Event)]
  }

  if (event.ask_settled && typeof event.ask_settled === 'object') {
    // Marked answered rather than removed: the next round appends the tool
    // result, and a card that vanished first would leave a gap mid-turn.
    const id = String((event.ask_settled as Event).id ?? '')
    return parts.map((part) =>
      part.type === 'ask' && part.id === id ? { ...part, answered: true } : part
    )
  }

  return parts
}

/** The answer text: every `text` part, which by construction excludes commentary. */
export function answerText(parts: readonly ChatPart[]): string {
  return parts
    .filter((part): part is { type: 'text'; text: string } => part.type === 'text')
    .map((part) => part.text)
    .join('')
}
