import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { DynamicIsland } from './DynamicIsland'
import { DEFAULT_ASSISTANT_STATE } from '../../../shared/runtime'

describe('DynamicIsland', () => {
  it('recesses ready into the line-only seed on the native surface', () => {
    const html = renderToStaticMarkup(<DynamicIsland state={DEFAULT_ASSISTANT_STATE} />)

    expect(html).toContain('island-seed')
    expect(html).toContain('island-seed-line')
    expect(html).not.toContain('Say Marvi')
  })

  it('keeps the full ready state in the control-center preview', () => {
    const html = renderToStaticMarkup(<DynamicIsland compact state={DEFAULT_ASSISTANT_STATE} />)

    expect(html).toContain('island-compact')
    expect(html).toContain('Say Marvi')
    expect(html).not.toContain('island-seed-line')
  })

  it('renders exact action details and both confirmation paths', () => {
    const html = renderToStaticMarkup(
      <DynamicIsland
        state={{
          ...DEFAULT_ASSISTANT_STATE,
          phase: 'confirmation',
          caption: 'Confirm action',
          confirmation: {
            token: 'token-1',
            action: 'Send email reply',
            detail: 'To Alex · Re: Project update'
          }
        }}
      />
    )

    expect(html).toContain('Send email reply')
    expect(html).toContain('To Alex · Re: Project update')
    expect(html).toContain('APPROVE')
    expect(html).toContain('DENY')
  })

  it('keeps YOLO visible while otherwise ready', () => {
    const html = renderToStaticMarkup(
      <DynamicIsland state={{ ...DEFAULT_ASSISTANT_STATE, yolo: true }} />
    )

    expect(html).toContain('YOLO')
    expect(html).not.toContain('island-seed-line')
  })
})
