import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { AccordionLoader } from './accordion-loader'

describe('AccordionLoader', () => {
  it('renders a status role with the block glyphs over a track', () => {
    const html = renderToStaticMarkup(<AccordionLoader />)

    expect(html).toContain('accordion-loader')
    expect(html).toContain('role="status"')
    expect(html).toContain('Loading')
    // the ░ track and the █ ▓ ▒ blocks
    expect(html).toContain('░')
    expect(html).toContain('█')
    expect(html).toContain('▓')
    expect(html).toContain('▒')
  })

  it('honors trackLength and custom blocks/track', () => {
    const html = renderToStaticMarkup(
      <AccordionLoader trackLength={6} blocks={['■', '▪', '·']} track="·" />
    )

    expect(html).toContain('--loader-width:6ch')
    expect(html).toContain('--loader-x:5ch')
    expect(html).toContain('■')
    expect(html).toContain('▪')
  })
})
