import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { MessageMatches } from './MessageMatches'

describe('messages found by the search box', () => {
  it('says nothing until the query is worth searching', () => {
    // One letter matches half a history; the effect does not even run.
    expect(renderToStaticMarkup(<MessageMatches activeId="a" onSelect={() => {}} query="h" />)).toBe(
      ''
    )
    expect(renderToStaticMarkup(<MessageMatches activeId="a" onSelect={() => {}} query="  " />)).toBe(
      ''
    )
  })

  it('renders nothing before results arrive', () => {
    // Static render: the search is an effect, so this is the empty state.
    expect(
      renderToStaticMarkup(<MessageMatches activeId="a" onSelect={() => {}} query="hotel" />)
    ).toBe('')
  })
})
