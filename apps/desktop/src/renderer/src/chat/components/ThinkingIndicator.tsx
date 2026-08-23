/** Animated "Marvi is typing" placeholder shown while a reply is in flight. */
export function ThinkingIndicator(): React.JSX.Element {
  return (
    <div className="chat-turn chat-assistant chat-working" role="status">
      <div className="chat-turn-head">
        <span className="chat-role">MARVI</span>
      </div>
      <div className="chat-thinking" aria-label="Marvi is thinking">
        <span className="chat-thinking-mark" aria-hidden="true" />
        <span>WORKING</span>
      </div>
    </div>
  )
}
