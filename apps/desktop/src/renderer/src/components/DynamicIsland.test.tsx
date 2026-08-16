import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { DynamicIsland } from './DynamicIsland'

describe('DynamicIsland', () => {
  it('recesses ready into the line-only seed on the native surface', () => {
    const html = renderToStaticMarkup(
      <DynamicIsland state={{ phase: 'ready', caption: 'Say Marvi', level: 0.18 }} />
    )

    expect(html).toContain('island-seed')
    expect(html).toContain('island-seed-line')
    expect(html).not.toContain('Say Marvi')
  })

  it('keeps the full ready state in the control-center preview', () => {
    const html = renderToStaticMarkup(
      <DynamicIsland compact state={{ phase: 'ready', caption: 'Say Marvi', level: 0.18 }} />
    )

    expect(html).toContain('island-compact')
    expect(html).toContain('Say Marvi')
    expect(html).not.toContain('island-seed-line')
  })
})
