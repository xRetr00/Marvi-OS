import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { MarviAvatar } from '../../components/ui/avatar'

describe('MarviAvatar', () => {
  it('renders', () => {
    const html = renderToStaticMarkup(<MarviAvatar />)
    console.log('AVATAR HTML:', html)
    expect(html).toContain('marvi-avatar')
  })
})
