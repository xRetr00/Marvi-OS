/**
 * "Marvi is thinking", and the rest of the live activity lines.
 *
 * Small, dim, shimmering, and scrambling into whatever it says next. It used
 * to be plain bold text at body size, which made a status line the loudest
 * thing in the transcript -- louder than the answer it was waiting for.
 */

import { useScramble } from './scramble'

export function ActivityLabel({ live, text }: { live: boolean; text: string }): React.JSX.Element {
  const scrambled = useScramble(text)
  return (
    <span
      className={live ? 'chat-scaffold-label is-live' : 'chat-scaffold-label'}
      // The settling characters are decoration; a screen reader gets the real
      // words, and gets them once rather than on every frame.
      aria-label={text}
    >
      <span aria-hidden="true">{live ? scrambled : text}</span>
    </span>
  )
}
