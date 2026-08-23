export type PetSide = 'left' | 'right'
export type PetScale = 0.4 | 0.5 | 0.7 | 1

export interface PetPreferences {
  enabled: boolean
  displayId: number | null
  side: PetSide
  scale: PetScale
  position: PointLike | null
}

export interface RectangleLike {
  x: number
  y: number
  width: number
  height: number
}

export interface PointLike {
  x: number
  y: number
}

export const PET_CELL_SIZE = { width: 192, height: 208 } as const
export const PET_CONTROL_HEIGHT = 64
export const DEFAULT_PET_PREFERENCES: PetPreferences = {
  enabled: true,
  displayId: null,
  side: 'right',
  scale: 0.5,
  position: null
}

export function normalizePetPreferences(value: unknown): PetPreferences {
  if (!value || typeof value !== 'object') return { ...DEFAULT_PET_PREFERENCES }
  const candidate = value as Partial<PetPreferences>
  return {
    enabled: typeof candidate.enabled === 'boolean' ? candidate.enabled : true,
    displayId:
      candidate.displayId === null || Number.isInteger(candidate.displayId)
        ? (candidate.displayId ?? null)
        : null,
    side: candidate.side === 'left' ? 'left' : 'right',
    scale: [0.4, 0.5, 0.7, 1].includes(candidate.scale as number)
      ? (candidate.scale as PetScale)
      : DEFAULT_PET_PREFERENCES.scale,
    position:
      candidate.position &&
      Number.isFinite(candidate.position.x) &&
      Number.isFinite(candidate.position.y)
        ? { x: Math.round(candidate.position.x), y: Math.round(candidate.position.y) }
        : null
  }
}

export function petWindowBounds(
  workArea: RectangleLike,
  preferences: Pick<PetPreferences, 'side' | 'scale' | 'position'>,
  margin = 18
): RectangleLike {
  const width = Math.round(PET_CELL_SIZE.width * preferences.scale)
  const height = Math.round((PET_CELL_SIZE.height + PET_CONTROL_HEIGHT) * preferences.scale)
  const anchored = {
    x: preferences.side === 'left' ? workArea.x + margin : workArea.x + workArea.width - width - margin,
    y: workArea.y + workArea.height - height - margin
  }
  const position = preferences.position ?? anchored
  return {
    x: Math.min(Math.max(position.x, workArea.x), workArea.x + Math.max(0, workArea.width - width)),
    y: Math.min(Math.max(position.y, workArea.y), workArea.y + Math.max(0, workArea.height - height)),
    width,
    height
  }
}

/** The native host reserves transparent room beneath the atlas cell for its
 * status and hover controls. Gaze calculations must still use the sprite. */
export function petSpriteBounds(bounds: RectangleLike): RectangleLike {
  return {
    ...bounds,
    height: Math.min(
      bounds.height,
      Math.round((bounds.width * PET_CELL_SIZE.height) / PET_CELL_SIZE.width)
    )
  }
}

export function pointInBounds(bounds: RectangleLike, point: PointLike): boolean {
  return (
    point.x >= bounds.x &&
    point.x < bounds.x + bounds.width &&
    point.y >= bounds.y &&
    point.y < bounds.y + bounds.height
  )
}

/** Quantize the cursor into the atlas' 16 gaze directions. Null is the
 * centered dead zone, which lets the renderer fall back to its state loop. */
export function petLookDirection(
  bounds: RectangleLike,
  cursor: PointLike,
  deadZone = 28
): number | null {
  const dx = cursor.x - (bounds.x + bounds.width / 2)
  const dy = cursor.y - (bounds.y + bounds.height * 0.38)
  if (Math.hypot(dx, dy) <= deadZone) return null
  // V2 direction 0 is up and advances clockwise in 22.5° steps.
  const degrees = (Math.atan2(dx, -dy) * 180) / Math.PI
  return Math.round(((degrees + 360) % 360) / 22.5) % 16
}
