/**
 * A horizontal rule in the ASCII idiom.
 *
 * This replaces a literal `+------------------------------+` that appeared
 * fifteen times. The string was thirty-two characters wide whatever the panel
 * was, so on anything wider it read as a stray box floating mid-page rather
 * than as a rule — and two of them either side of a section that happened to be
 * empty (Setup, while the catalog loads) looked like a maze.
 *
 * The corners are real characters, and the dashes are a long run clipped to the
 * container. In a monospace face that is an honest character rule at any width,
 * which is what the ASCII look was after.
 */
const DASHES = '-'.repeat(400)

export function AsciiRule(): React.JSX.Element {
  return (
    <div aria-hidden="true" className="ascii-rule">
      <span>+</span>
      <span className="ascii-rule-fill">{DASHES}</span>
      <span>+</span>
    </div>
  )
}
