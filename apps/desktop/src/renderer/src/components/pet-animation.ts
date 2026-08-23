import type { AssistantState } from '../../../shared/runtime'

export interface PetFrame {
  row: number
  column: number
  duration: number
}

function sequence(row: number, durations: number[]): PetFrame[] {
  return durations.map((duration, column) => ({ row, column, duration }))
}

const PET_ANIMATIONS = {
  idle: sequence(0, [280, 110, 110, 140, 140, 320]),
  runRight: sequence(1, [120, 120, 120, 120, 120, 120, 120, 220]),
  wave: sequence(3, [140, 140, 140, 280]),
  jump: sequence(4, [140, 140, 140, 140, 280]),
  failed: sequence(5, [140, 140, 140, 140, 140, 140, 140, 240]),
  wait: sequence(6, [150, 150, 150, 150, 150, 260]),
  run: sequence(7, [120, 120, 120, 120, 120, 220]),
  review: sequence(8, [150, 150, 150, 150, 150, 280])
} as const

export function petAnimationFor(phase: AssistantState['phase']): readonly PetFrame[] {
  switch (phase) {
    case 'wake':
      return PET_ANIMATIONS.wave
    case 'thinking':
      return PET_ANIMATIONS.run
    case 'speaking':
      return PET_ANIMATIONS.review
    case 'action':
      return PET_ANIMATIONS.runRight
    case 'notification':
      return PET_ANIMATIONS.jump
    case 'confirmation':
      return PET_ANIMATIONS.wait
    case 'error':
      return PET_ANIMATIONS.failed
    default:
      return PET_ANIMATIONS.idle
  }
}

export function petGazeFrame(direction: number): PetFrame {
  const normalized = ((Math.round(direction) % 16) + 16) % 16
  return {
    row: normalized < 8 ? 9 : 10,
    column: normalized % 8,
    duration: 0
  }
}
