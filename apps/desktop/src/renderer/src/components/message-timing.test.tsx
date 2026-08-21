import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { AbstractIcon } from './abstract-icon'
import { MessageTiming } from './message-timing'

describe('MessageTiming', () => {
  it('renders every supplied stat without prescribing what it measures', () => {
    const html = renderToStaticMarkup(
      <MessageTiming
        stats={[
          { label: 'TOKENS', value: '1,240' },
          { label: 'SESSION', value: '04:12' }
        ]}
      />
    )
    expect(html).toContain('data-slot="message-timing"')
    expect(html).toContain('TOKENS')
    expect(html).toContain('1,240')
    expect(html).toContain('04:12')
  })

  it('marks live values without changing their text', () => {
    const html = renderToStaticMarkup(
      <MessageTiming streaming stats={[{ label: 'LAST', value: '—' }]} />
    )
    expect(html).toContain('is-streaming')
    expect(html).toContain('LAST')
  })
})

describe('AbstractIcon', () => {
  it('is decorative and inherits the interface color', () => {
    const html = renderToStaticMarkup(<AbstractIcon name="voice" />)
    expect(html).toContain('aria-hidden="true"')
    expect(html).toContain('stroke="currentColor"')
  })
})
