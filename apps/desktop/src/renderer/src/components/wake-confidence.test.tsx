import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { DataStream } from './ui/data-stream'
import { WakeConfidence } from './wake-confidence'
import { asEntries, loudest, readable, usableThreshold } from './wake-confidence-utils'

// The three real false alarms, from state/wake.json.
const recent = [
  { at: 1788985798.868, confidence: 0.3963 },
  { at: 1788982859.733, confidence: 0.4772 },
  { at: 1788982323.845, confidence: 0.475 }
]

describe('choosing a wake threshold', () => {
  it('accepts only what the listener itself accepts', () => {
    // `threshold()` filters to > 0 and <= 1 and silently falls back to the
    // default outside that, so anything else would appear saved and do nothing.
    expect(usableThreshold('0.5')).toBe(0.5)
    expect(usableThreshold('0.42')).toBe(0.42)
    expect(usableThreshold('1')).toBe(1)
    for (const refused of ['0', '-1', '1.5', '', '   ', 'abc']) {
      expect(usableThreshold(refused), refused).toBeNull()
    }
  })

  it('shows three decimals, because that is where the differences are', () => {
    // 0.475 and 0.477 were two separate false alarms.
    expect(readable(0.475)).toBe('0.475')
    expect(readable(0.4772)).toBe('0.477')
  })

  it('names the loudest false alarm, which is the number to beat', () => {
    expect(loudest(recent)).toBe(0.4772)
    expect(loudest([])).toBe(0)
  })

  it('marks which detections actually woke her, at the current threshold', () => {
    // At 0.35 all three fired; at 0.5 none would have. That contrast is the
    // whole argument for changing the number.
    const at035 = asEntries(recent, 0.35)
    expect(at035.every((one) => one.text === 'woke her')).toBe(true)
    expect(at035.every((one) => one.tone === 'warning')).toBe(true)

    const at05 = asEntries(recent, 0.5)
    expect(at05.every((one) => one.text === 'below the line')).toBe(true)
  })

  it('reads downwards, oldest first', () => {
    const entries = asEntries(recent, 0.35)
    expect(entries.map((one) => one.hint)).toEqual(['0.475', '0.477', '0.396'])
  })
})

describe('the control', () => {
  it('offers a typed number rather than three fixed choices', () => {
    const html = renderToStaticMarkup(
      <WakeConfidence heardTotal={3} onChange={() => {}} recent={recent} threshold={0.35} />
    )
    expect(html).toContain('type="number"')
    expect(html).toContain('value="0.35"')
    expect(html).toContain('step="0.01"')
    // And the evidence beside it.
    expect(html).toContain('0.477')
    expect(html).toContain('Wake detections')
  })

  it('says what a fresh listener has not yet recorded', () => {
    const html = renderToStaticMarkup(
      <WakeConfidence heardTotal={0} onChange={() => {}} recent={[]} threshold={0.5} />
    )
    expect(html).toContain('has not woken since the listener started')
  })
})

describe('the stream', () => {
  it('counts what it has revealed against the total', () => {
    const html = renderToStaticMarkup(
      <DataStream entries={[{ text: 'one' }, { text: 'two' }]} title="LOG" />
    )
    expect(html).toContain('LOG')
    expect(html).toContain('0/2')
  })

  it('says so when there is nothing, rather than showing an empty box', () => {
    const html = renderToStaticMarkup(<DataStream empty="Quiet." entries={[]} />)
    expect(html).toContain('Quiet.')
  })

  it('is a log for anything not looking at it', () => {
    const html = renderToStaticMarkup(<DataStream entries={[{ text: 'x' }]} title="LOG" />)
    expect(html).toContain('role="log"')
    expect(html).toContain('aria-live="polite"')
  })
})
