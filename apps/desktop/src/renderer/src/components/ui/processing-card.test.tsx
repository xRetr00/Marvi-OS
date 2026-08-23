import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { ProcessingCard } from './processing-card'

describe('ProcessingCard', () => {
  it('does not invent a percentage for indeterminate work', () => {
    const html = renderToStaticMarkup(<ProcessingCard detail="Reading data" title="Loading" />)
    expect(html).toContain('aria-busy="true"')
    expect(html).toContain('indeterminate')
    expect(html).not.toContain('aria-valuenow')
  })

  it('shows real progress and stages when supplied', () => {
    const html = renderToStaticMarkup(
      <ProcessingCard
        detail="Installing"
        progress={42}
        stages={[{ label: 'Download', state: 'active' }]}
        title="Model setup"
      />
    )
    expect(html).toContain('aria-valuenow="42"')
    expect(html).toContain('width:42%')
    expect(html).toContain('Download')
  })
})
