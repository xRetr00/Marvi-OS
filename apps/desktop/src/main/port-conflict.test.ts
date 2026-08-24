import { describe, expect, it } from 'vitest'

/**
 * "Address already in use" is the one service failure whose cause is another
 * process entirely, so it is the one worth naming instead of retrying past.
 *
 * The Gateway wrote `[Errno 10048]` and exited every ten seconds for an hour
 * without once saying what held the port. It was a Gateway from a second
 * checkout, running since the previous evening — invisible from inside Marvi,
 * because the stray sweep is scoped to this install root and correctly leaves
 * another checkout alone.
 */
describe('recognising a port conflict', () => {
  const pattern = /10048|EADDRINUSE|address already in use/i

  it('recognises the Windows error the Gateway actually writes', () => {
    expect(
      pattern.test(
        "ERROR: [Errno 10048] error while attempting to bind on address ('127.0.0.1', 8765)"
      )
    ).toBe(true)
  })

  it('recognises the posix and node spellings too', () => {
    expect(pattern.test('OSError: [Errno 98] Address already in use')).toBe(true)
    expect(pattern.test('Error: listen EADDRINUSE: address already in use')).toBe(true)
  })

  it('does not fire on an ordinary crash', () => {
    expect(pattern.test('ModuleNotFoundError: No module named marvi_gateway')).toBe(false)
    expect(pattern.test('Traceback (most recent call last)')).toBe(false)
  })
})
