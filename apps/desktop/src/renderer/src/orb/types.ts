// Orb state + size types. Trimmed from the vendored thinking-orbs `types.ts`
// (the theme + React prop types are unused — Marvi is always dark and ships
// its own component). See docs/UPSTREAM.md for provenance.

/**
 * The nine shipped states — each a hand-tuned dotted animation:
 * working, searching, solving, listening, connecting, weaving, composing,
 * breathing, shaping.
 */
export type OrbState =
  | 'working'
  | 'searching'
  | 'solving'
  | 'listening'
  | 'connecting'
  | 'weaving'
  | 'composing'
  | 'breathing'
  | 'shaping'

/** Tuned size presets: 64 (avatar scale) and 20 (inline scale). */
export type OrbSize = 64 | 20
