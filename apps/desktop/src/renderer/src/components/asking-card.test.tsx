import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Question } from '../../../shared/asking'
import { AskingCard } from './asking-card'

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

const settleAsking = vi.fn()

beforeEach(() => {
  settleAsking.mockReset().mockResolvedValue({ ok: true, state: 'answered' })
  // @ts-expect-error -- the renderer's bridge, stubbed for the test
  window.marvi = { settleAsking }
})

describe('the question Marvi puts on screen', () => {
  it('asks the question and offers the three real outcomes', () => {
    const html = renderToStaticMarkup(<AskingCard question={question} />)
    expect(html).toContain('How do you spell your surname?')
    expect(html).toContain('Surname')
    // Answering, closing, and never again are three different things.
    expect(html).toContain('Send')
    expect(html).toContain('Not now')
    expect(html).toContain('Don&#x27;t ask')
  })

  it('will not send an empty answer', async () => {
    // An empty box reporting itself answered is the worst outcome: Marvi files
    // nothing and never asks again.
    render(<AskingCard question={question} />)
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()

    fireEvent.change(screen.getByRole('textbox'), { target: { value: '   ' } })
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Ibrahim' } })
    expect(screen.getByRole('button', { name: 'Send' })).toBeEnabled()
  })

  it('sends a trimmed answer', async () => {
    const settled = vi.fn()
    render(<AskingCard onSettled={settled} question={question} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '  Ibrahim  ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(settleAsking).toHaveBeenCalledWith('q1', 'answered', 'Ibrahim'))
    await waitFor(() => expect(settled).toHaveBeenCalledWith('answered'))
  })

  it('separates closing the box from refusing the subject', async () => {
    // "Not now" earns one spoken follow-up. "Don't ask" is permanent. Sending
    // the same state for both would make the gentle one irreversible.
    const { unmount } = render(<AskingCard question={question} />)
    fireEvent.click(screen.getByRole('button', { name: 'Not now' }))
    await waitFor(() => expect(settleAsking).toHaveBeenCalledWith('q1', 'dismissed', ''))
    unmount()

    settleAsking.mockClear()
    render(<AskingCard question={question} />)
    fireEvent.click(screen.getByRole('button', { name: /Don.t ask/ }))
    await waitFor(() => expect(settleAsking).toHaveBeenCalledWith('q1', 'declined', ''))
  })

  it('closes the box on Escape rather than swallowing the key', async () => {
    render(<AskingCard question={question} />)
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Escape' })
    await waitFor(() => expect(settleAsking).toHaveBeenCalledWith('q1', 'dismissed', ''))
  })

  it('keeps the question on screen when sending fails', async () => {
    // Clearing it would look like it went through, and Marvi would sit waiting
    // for an answer that never arrived.
    settleAsking.mockRejectedValue(new Error('gateway down'))
    const settled = vi.fn()
    render(<AskingCard onSettled={settled} question={question} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Ibrahim' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('did not send'))
    expect(settled).not.toHaveBeenCalled()
    expect(screen.getByRole('textbox')).toHaveValue('Ibrahim')
  })
})
