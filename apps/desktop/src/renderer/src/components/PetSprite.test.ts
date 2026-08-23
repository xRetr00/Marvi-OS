import { describe, expect, it } from 'vitest'

import { petAnimationFor, petGazeFrame } from './pet-animation'

describe('petAnimationFor', () => {
  it('maps assistant activity to a meaningful atlas row', () => {
    expect(petAnimationFor('ready')[0].row).toBe(0)
    expect(petAnimationFor('wake')[0].row).toBe(3)
    expect(petAnimationFor('thinking')[0].row).toBe(7)
    expect(petAnimationFor('speaking')[0].row).toBe(8)
    expect(petAnimationFor('action')[0].row).toBe(1)
    expect(petAnimationFor('notification')[0].row).toBe(4)
    expect(petAnimationFor('confirmation')[0].row).toBe(6)
    expect(petAnimationFor('error')[0].row).toBe(5)
  })
})

describe('petGazeFrame', () => {
  it('maps all sixteen directions across the final two rows', () => {
    expect(petGazeFrame(0)).toMatchObject({ row: 9, column: 0 })
    expect(petGazeFrame(7)).toMatchObject({ row: 9, column: 7 })
    expect(petGazeFrame(8)).toMatchObject({ row: 10, column: 0 })
    expect(petGazeFrame(15)).toMatchObject({ row: 10, column: 7 })
    expect(petGazeFrame(16)).toMatchObject({ row: 9, column: 0 })
  })
})
