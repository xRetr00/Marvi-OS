import { StreamActivity } from './ReasoningDisclosure'

/** The tail-only placeholder before the first visible reasoning or answer token. */
export function ThinkingIndicator({ startedAt }: { startedAt: string }): React.JSX.Element {
  return (
    <div aria-label="Marvi is thinking" className="chat-turn chat-assistant chat-working">
      <span className="sr-only">MARVI</span>
      <StreamActivity label="Thinking" startedAt={startedAt} />
    </div>
  )
}
