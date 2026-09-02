import type { Rectangle } from 'electron'

export interface IslandContentSize {
  width: number
  height: number
}

export type IslandAlignment = 'left' | 'center' | 'right'
export type IslandInteractionMode = 'passive' | 'hover' | 'interactive'

export interface IslandPlacement {
  displayId: number | null
  alignment: IslandAlignment
}

// Two pixels are enough to preserve the hairline edge without leaving a
// noticeable transparent capture stage around the always-on-top surface.
export const ISLAND_WINDOW_INSET = 2
export const ISLAND_MIN_CONTENT_SIZE: IslandContentSize = { width: 38, height: 8 }
export const ISLAND_SEED_CONTENT_SIZE: IslandContentSize = { width: 76, height: 8 }
export const ISLAND_MAX_CONTENT_SIZE: IslandContentSize = { width: 360, height: 92 }

export function normalizeIslandInteractionMode(value: unknown): IslandInteractionMode {
  if (value === 'hover' || value === 'interactive') return value
  return 'passive'
}

export function normalizeIslandContentSize(value: unknown): IslandContentSize | null {
  if (!value || typeof value !== 'object') return null

  const candidate = value as Partial<IslandContentSize>
  if (!Number.isFinite(candidate.width) || !Number.isFinite(candidate.height)) return null

  return {
    width: Math.min(
      ISLAND_MAX_CONTENT_SIZE.width,
      Math.max(ISLAND_MIN_CONTENT_SIZE.width, Math.round(candidate.width as number))
    ),
    height: Math.min(
      ISLAND_MAX_CONTENT_SIZE.height,
      Math.max(ISLAND_MIN_CONTENT_SIZE.height, Math.round(candidate.height as number))
    )
  }
}

export function islandWindowBounds(
  workArea: Rectangle,
  contentSize: IslandContentSize,
  alignment: IslandAlignment = 'center'
): Rectangle {
  const width = contentSize.width + ISLAND_WINDOW_INSET * 2
  const height = contentSize.height + ISLAND_WINDOW_INSET * 2
  const edgeInset = 18
  const xByAlignment = {
    left: workArea.x + edgeInset,
    center: workArea.x + (workArea.width - width) / 2,
    right: workArea.x + workArea.width - width - edgeInset
  }

  return {
    x: Math.round(xByAlignment[alignment]),
    // Every presentation grows from the work-area edge like a physical notch.
    // No detached six-pixel gap remains above active states.
    y: Math.round(workArea.y),
    width,
    height
  }
}
