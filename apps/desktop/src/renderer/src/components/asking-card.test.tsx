import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { Question } from '../../../shared/asking'
import { AskingCard } from './asking-card'
import { readyToSend } from './asking'

const question: Question = {
  id: 'q1',
  question: 'How do you spell your surname?',
  about: 'name',
  placeholder: 'Surname',
  state: 'open',
  answer: '',
  asked_at: 0,
  settled_at: 0
}

describe('the question Marvi puts on screen', () => {
  it('asks the question and offers the three real outcomes', () => {
    const html = renderToStaticMarkup(<AskingCard question={question} />)
    expect(html).toContain('How do you spell your surname?')
    expect(html).toContain('Surname')
    // Answering, closing it, and never again are three different things, and
    // collapsing them into one ✕ would make the accidental click permanent.
    expect(html).toContain('Send')
    expect(html).toContain('Not now')
    expect(html).toContain('Don&#x27;t ask')
  })

  it('cannot send until something is typed', () => {
    const html = renderToStaticMarkup(<AskingCard question={question} />)
    // The Send button ships disabled, so an empty box cannot report itself
    // answered — which would settle the question and stop the follow-up.
    expect(html).toMatch(/class="asking-send"[^>]*disabled/)
  })

  it('falls back to a generic hint when the question carries none', () => {
    const html = renderToStaticMarkup(
      <AskingCard question={{ ...question, placeholder: '' }} />
    )
    expect(html).toContain('Type your answer')
  })

  it('labels the box with the question, for anyone not reading the screen', () => {
    const html = renderToStaticMarkup(<AskingCard question={question} />)
    expect(html).toContain('aria-label="How do you spell your surname?"')
    expect(html).toContain('aria-label="A question from Marvi"')
  })
})

describe('what counts as an answer', () => {
  it('treats whitespace as nothing', () => {
    // Marvi would file nothing, mark it settled, and never ask again.
    expect(readyToSend('')).toBe('')
    expect(readyToSend('   ')).toBe('')
    expect(readyToSend('\n\t ')).toBe('')
  })

  it('trims what is sent', () => {
    expect(readyToSend('  Ibrahim  ')).toBe('Ibrahim')
    expect(readyToSend('Ibrahim')).toBe('Ibrahim')
  })
})
