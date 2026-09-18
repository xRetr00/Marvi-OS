import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { ImageGeneration } from './ImageGeneration'
import { prettySize } from '../image-size'

describe('a picture being drawn', () => {
  it('stands in for the image, with the prompt and the size', () => {
    const markup = renderToStaticMarkup(
      <ImageGeneration prompt="a calm mountain lake at dawn" resolution="1024 × 1024" />
    )
    expect(markup).toContain('Generating image')
    expect(markup).toContain('a calm mountain lake at dawn')
    expect(markup).toContain('1024 × 1024')
    // A screen reader is told what is being drawn, not just that something is.
    expect(markup).toContain('aria-label="Generating an image of a calm mountain lake at dawn"')
  })

  it('reads a size the way a person writes it', () => {
    expect(prettySize('1024x1024')).toBe('1024 × 1024')
    expect(prettySize('1536 X 1024')).toBe('1536 × 1024')
    expect(prettySize('auto')).toBe('auto')
    expect(prettySize(undefined)).toBe('1024 × 1024')
  })
})
