import type { Rectangle } from 'electron'

export interface IslandContentSize {
  width: number
  height: number
}

export type IslandAlignment = 'left' | 'center' | 'right'

export interface IslandPlacement {
  displayId: number | null
  alignment: IslandAlignment
}

export const ISLAND_WINDOW_INSET = 12
export const ISLAND_MIN_CONTENT_SIZE: IslandContentSize = { width: 76, height: 8 }
export const ISLAND_MAX_CONTENT_SIZE: IslandContentSize = { width: 360, height: 92 }

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
  topOffset = 6,
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
    y: Math.round(
      workArea.y +
        (contentSize.width === ISLAND_MIN_CONTENT_SIZE.width &&
        contentSize.height === ISLAND_MIN_CONTENT_SIZE.height
          ? 0
          : topOffset)
    ),
    width,
    height
  }
}
