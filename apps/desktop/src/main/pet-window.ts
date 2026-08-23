export type PetSide = 'left' | 'right'
export type PetScale = 0.75 | 1

export interface PetPreferences {
  enabled: boolean
  displayId: number | null
  side: PetSide
  scale: PetScale
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
export const DEFAULT_PET_PREFERENCES: PetPreferences = {
  enabled: true,
  displayId: null,
  side: 'right',
  scale: 1
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
    scale: candidate.scale === 0.75 ? 0.75 : 1
  }
}

export function petWindowBounds(
  workArea: RectangleLike,
  preferences: Pick<PetPreferences, 'side' | 'scale'>,
  margin = 18
): RectangleLike {
  const width = Math.round(PET_CELL_SIZE.width * preferences.scale)
  const height = Math.round(PET_CELL_SIZE.height * preferences.scale)
  return {
    x:
      preferences.side === 'left'
        ? workArea.x + margin
        : workArea.x + workArea.width - width - margin,
    y: workArea.y + workArea.height - height - margin,
    width,
    height
  }
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
  const degrees = (Math.atan2(dy, dx) * 180) / Math.PI
  return Math.round(((degrees + 360) % 360) / 22.5) % 16
}
