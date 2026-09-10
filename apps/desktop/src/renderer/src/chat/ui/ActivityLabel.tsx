/**
 * "Marvi is thinking", and the rest of the live activity lines.
 *
 * Small, dim, and shimmering. Nothing else: it had a five-glyph spinner and a
 * settling-text effect, and both were louder than the answer they were waiting
 * for. A status line's whole job is to say "not yet" without taking attention
 * away from the thing that will replace it.
 */

export function ActivityLabel({ live, text }: { live: boolean; text: string }): React.JSX.Element {
  return (
    <span className={live ? 'chat-scaffold-label is-live' : 'chat-scaffold-label'}>{text}</span>
  )
}
