import { describe, expect, it } from 'vitest'
import { describeFailure } from './MessageError'

describe('describeFailure', () => {
  it('extracts a useful credit message from a provider payload', () => {
    const failure = describeFailure('No provider could start a stream; last error: openrouter rejected (402): {"error":{"message":"This request requires more credits, or fewer max_tokens.","code":402}}')
    expect(failure.title).toBe('Provider credits are exhausted')
    expect(failure.detail).not.toContain('{"error"')
    expect(failure.technical).toContain('openrouter rejected')
  })
  it('gives rate limits and unknown failures distinct summaries', () => {
    expect(describeFailure('HTTP 429 Too many requests').title).toBe('Provider is busy')
    expect(describeFailure('model stopped unexpectedly').title).toBe('Marvi could not finish')
  })
})
