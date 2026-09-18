import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { WorkflowsPage } from './workflows-page'

/**
 * Rendered without a Gateway, which is the state the page is in for the first
 * moment of every launch: effects have not run, so nothing has been fetched.
 * What it says then still has to be true and still has to be legible.
 */
const markup = renderToStaticMarkup(<WorkflowsPage />)

describe('the workflows page', () => {
  it('has a column for every state a job can be in', () => {
    for (const label of ['To do', 'Running', 'Needs you', 'Blocked', 'Done', 'Failed']) {
      expect(markup).toContain(label)
    }
  })

  it('marks only the two columns that want something from the person', () => {
    // `is-wanted` is the page's one use of the accent colour, and it is earned
    // by a column with cards in it -- so with no board yet, nothing is marked.
    expect(markup).not.toContain('is-wanted')
    expect(markup).toContain('wf-column')
  })

  it('says an action still goes through confirmation', () => {
    // The thing a person is most likely to assume wrong about an automation:
    // that it is a private way to make a tool call. It is not.
    expect(markup).toContain('asks you first')
  })

  it('offers no rules of its own and says why there are none', () => {
    expect(markup).toContain('cannot switch on for herself')
  })

  it('survives having no Gateway to talk to', () => {
    expect(markup).toContain('wf-page')
    expect(markup).not.toContain('undefined')
  })
})
