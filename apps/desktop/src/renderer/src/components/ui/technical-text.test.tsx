import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { TechnicalText } from './technical-text'

describe('TechnicalText', () => {
  it('isolates mixed-direction identifiers as LTR', () => {
    expect(renderToStaticMarkup(<TechnicalText>C:\Marvi\model-v2</TechnicalText>)).toBe(
      '<bdi dir="ltr">C:\\Marvi\\model-v2</bdi>'
    )
  })
})
