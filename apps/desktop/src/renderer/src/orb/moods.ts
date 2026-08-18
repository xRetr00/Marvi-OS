// The orb's colour vocabulary, split out from the component because it is
// data and two functions rather than a view — and because Fast Refresh only
// works when a file exports components alone.
//
// The orb is the fastest signal on the Voice page: colour is legible across a
// room, and a label has to be read.

export type RGB = [number, number, number]

// Depth ramps (0 = cool/far, 1 = hot/near), one per mood. The orb says what
// Marvi is doing before any label does: you catch colour from across a room and
// you have to be looking at text to read it.
export type Ramp = Array<[number, RGB]>

export const RAMPS: Record<string, Ramp> = {
  // Resting: the original orange → red → pink → magenta.
  idle: [
    [0.0, [0xa8, 0x55, 0xf7]],
    [0.33, [0xec, 0x48, 0x99]],
    [0.66, [0xef, 0x44, 0x44]],
    [1.0, [0xf9, 0x73, 0x16]]
  ],
  // Listening: cool and awake, so it reads as "your turn".
  listening: [
    [0.0, [0x1e, 0x3a, 0x8a]],
    [0.4, [0x25, 0x63, 0xeb]],
    [0.75, [0x38, 0xbd, 0xf8]],
    [1.0, [0xa5, 0xf3, 0xfc]]
  ],
  // Thinking: held, low-energy violet.
  thinking: [
    [0.0, [0x31, 0x27, 0x6b]],
    [0.5, [0x6d, 0x28, 0xd9]],
    [1.0, [0xc0, 0x84, 0xfc]]
  ],
  // Speaking: warm and bright, the loudest state.
  speaking: [
    [0.0, [0x7c, 0x2d, 0x12]],
    [0.4, [0xea, 0x58, 0x0c]],
    [0.75, [0xfb, 0xbf, 0x24]],
    [1.0, [0xfe, 0xf3, 0xc7]]
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
