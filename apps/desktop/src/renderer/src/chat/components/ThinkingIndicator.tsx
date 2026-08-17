/** Animated "Marvi is typing" placeholder shown while a reply is in flight. */
export function ThinkingIndicator(): React.JSX.Element {
  return (
    <div className="chat-turn chat-assistant">
      <div className="chat-turn-head">
        <span className="chat-role">MARVI</span>
      </div>
      <div className="chat-thinking" aria-label="Marvi is thinking">
        <span />
        <span />
        <span />
      </div>
    </div>
  )
}
