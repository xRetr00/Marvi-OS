import { useEffect, useRef } from 'react'

import type { AssistantState } from '../../../shared/runtime'
import spritesheetUrl from '../assets/pet/marvi/spritesheet.webp'
import { petAnimationFor, petGazeFrame, type PetFrame } from './pet-animation'

const CELL_WIDTH = 192
const CELL_HEIGHT = 208

function drawFrame(canvas: HTMLCanvasElement, image: HTMLImageElement, frame: PetFrame): void {
  // Each atlas cell already matches the full-size window. A 2x backing canvas
  // quadruples the draw work but cannot recover detail absent from the source.
  if (canvas.width !== CELL_WIDTH || canvas.height !== CELL_HEIGHT) {
    canvas.width = CELL_WIDTH
    canvas.height = CELL_HEIGHT
  }
  const context = canvas.getContext('2d')
  if (!context) return
  context.clearRect(0, 0, CELL_WIDTH, CELL_HEIGHT)
  context.imageSmoothingEnabled = true
  context.imageSmoothingQuality = 'high'
  context.drawImage(
    image,
    frame.column * CELL_WIDTH,
    frame.row * CELL_HEIGHT,
    CELL_WIDTH,
    CELL_HEIGHT,
    0,
    0,
    CELL_WIDTH,
    CELL_HEIGHT
  )
}

export function PetSprite({
  phase,
  lookDirection
}: {
  phase: AssistantState['phase']
  lookDirection: number | null
}): React.JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const image = new Image()
    let timeout: ReturnType<typeof setTimeout> | undefined
    let animationFrame = 0
    let cancelled = false
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const frames = lookDirection === null ? petAnimationFor(phase) : [petGazeFrame(lookDirection)]

    image.onload = (): void => {
      let index = 0
      const advance = (): void => {
        if (cancelled) return
        drawFrame(canvas, image, frames[index])
        if (reducedMotion || frames.length === 1) return
        timeout = setTimeout(() => {
          animationFrame = requestAnimationFrame(() => {
            index = (index + 1) % frames.length
            advance()
          })
        }, frames[index].duration)
      }
      advance()
    }
    image.src = spritesheetUrl

    return () => {
      cancelled = true
      if (timeout !== undefined) clearTimeout(timeout)
      cancelAnimationFrame(animationFrame)
    }
  }, [lookDirection, phase])

  return (
    <canvas
      aria-label={`Marvi pet — ${phase}`}
      className="pet-sprite"
      height={CELL_HEIGHT}
      ref={canvasRef}
      role="img"
      width={CELL_WIDTH}
    />
  )
}
