// The orb's colour vocabulary, split out from the component because it is
// data and two functions rather than a view — and because Fast Refresh only
// works when a file exports components alone.
//
// The shell stays monochrome and reserves blue for live status. Phase changes
// therefore alter intensity and depth, not the whole product palette.

export type RGB = [number, number, number]

// Depth ramps (0 = cool/far, 1 = hot/near), one per mood. The orb says what
// Marvi is doing before any label does: you catch colour from across a room and
// you have to be looking at text to read it.
export type Ramp = Array<[number, RGB]>

export const RAMPS: Record<string, Ramp> = {
  // Resting: cool graphite into bone.
  idle: [
    [0.0, [0x34, 0x38, 0x3d]],
    [0.55, [0x78, 0x7e, 0x86]],
    [1.0, [0xe7, 0xe7, 0xe3]]
  ],
  // Listening: cool and awake, so it reads as "your turn".
  listening: [
    [0.0, [0x0b, 0x35, 0x50]],
    [0.55, [0x14, 0x7e, 0xc1]],
    [1.0, [0xb8, 0xd9, 0xec]]
  ],
  // Thinking: denser steel, within the same status family.
  thinking: [
    [0.0, [0x19, 0x2c, 0x38]],
    [0.55, [0x3f, 0x78, 0x99]],
    [1.0, [0xd5, 0xe5, 0xee]]
  ],
  // Speaking: high-contrast bone with a restrained blue core.
  speaking: [
    [0.0, [0x0f, 0x4f, 0x75]],
    [0.45, [0x14, 0x7e, 0xc1]],
    [0.78, [0xb9, 0xd8, 0xea]],
    [1.0, [0xfa, 0xfa, 0xf8]]
  ],
  // Error: unmistakable, and not a colour any working state uses.
  error: [
    [0.0, [0x45, 0x0a, 0x0a]],
    [0.5, [0xb9, 0x1c, 0x1c]],
    [1.0, [0xf8, 0x71, 0x71]]
  ]
}

export const MOOD_FOR_PHASE: Record<string, string> = {
  listening: 'listening',
  wake: 'listening',
  thinking: 'thinking',
  speaking: 'speaking',
  error: 'error'
}

/** Blend two ramps, so a phase change is a sweep rather than a jump cut. */
export function blend(from: Ramp, to: Ramp, mix: number, t: number): RGB {
  const a = sample(from, t)
  const b = sample(to, t)
  return [
    Math.round(a[0] + (b[0] - a[0]) * mix),
    Math.round(a[1] + (b[1] - a[1]) * mix),
    Math.round(a[2] + (b[2] - a[2]) * mix)
  ]
}

function sample(stops: Ramp, t: number): RGB {
  const x = Math.max(0, Math.min(1, t))
  for (let i = 0; i < stops.length - 1; i += 1) {
    const [t0, c0] = stops[i]
    const [t1, c1] = stops[i + 1]
    if (x >= t0 && x <= t1) {
      const f = (x - t0) / (t1 - t0)
      return [
        Math.round(c0[0] + (c1[0] - c0[0]) * f),
        Math.round(c0[1] + (c1[1] - c0[1]) * f),
        Math.round(c0[2] + (c1[2] - c0[2]) * f)
      ]
    }
  }
  return stops[stops.length - 1][1]
}
