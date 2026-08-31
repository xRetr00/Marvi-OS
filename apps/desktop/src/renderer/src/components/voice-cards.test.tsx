/**
 * The two cards beside the orb.
 *
 * Both are built from Chat's own pieces rather than new ones, so these assert
 * the class names as well as the content: `status-context-meter` and
 * `chat-tool-section-head` are the same elements Chat draws, styled once. A
 * second visual language for the same two ideas is how a product starts
 * looking like two products.
 */
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { ActivityView, CalendarView, type VoiceActivity } from './voice-cards'

function activity(over: Partial<VoiceActivity> = {}): VoiceActivity {
  return { calls: [], running: 0, context: { used: 0, window: 0, turns: 0 }, ...over }
}

describe('the activity card', () => {
  it('shows how full the context is, on the meter Chat draws', () => {
    const html = renderToStaticMarkup(
      <ActivityView activity={activity({ context: { used: 4000, window: 16000, turns: 3 } })} />
    )

    expect(html).toContain('25%')
    expect(html).toContain('4k/16k')
    expect(html).toContain('status-context-meter')
  })

  it('says so rather than guessing when the window is unknown', () => {
    const html = renderToStaticMarkup(<ActivityView activity={activity()} />)

    expect(html).toContain('—%')
    expect(html).toContain('No tools used yet')
  })

  it('puts a running call above the fold, never behind the collapse', () => {
    // The question this page is open for is "is it stuck", and that one
    // cannot be one click away.
    const html = renderToStaticMarkup(
      <ActivityView
        activity={activity({
          calls: [
            {
              id: '1',
              tool: 'web_search',
              arguments: { query: 'fc 26' },
              outcome: 'running',
              ms: 0
            }
          ],
          running: 1
        })}
      />
    )

    expect(html).toContain('voice-card-live')
    expect(html).toContain('Web search')
    expect(html).toContain('1 running')
  })

  it('names the arguments beside the tool, not just the tool', () => {
    // "forgot something" and "forgot the right thing" look identical without
    // this, which is the whole reason a receipt carries its arguments.
    const html = renderToStaticMarkup(
      <ActivityView
        activity={activity({
          calls: [
            { id: '1', tool: 'memory_forget', arguments: { query: 'Zed' }, outcome: 'ok', ms: 120 }
          ]
        })}
      />
    )

    expect(html).toContain('query=Zed')
    expect(html).toContain('120ms')
    expect(html).toContain('chat-tool-section-head')
  })

  it('marks a failed call as failed', () => {
    const html = renderToStaticMarkup(
      <ActivityView
        activity={activity({
          calls: [{ id: '1', tool: 'room_set_light', arguments: {}, outcome: 'failed', ms: 40 }]
        })}
      />
    )

    expect(html).toContain('failed')
  })
})

describe('the calendar card', () => {
  const now = new Date('2026-09-01T09:00:00Z')

  it('says the calendar is not connected rather than showing nothing', () => {
    // Empty and not-connected look the same otherwise, and only one of them
    // is something the user can act on.
    const html = renderToStaticMarkup(
      <CalendarView calendar={{ connected: false, events: [] }} now={now} />
    )

    expect(html).toContain('Calendar not connected')
  })

  it('draws the month even with nothing on it', () => {
    // An empty list is a card that looks broken. A month with no dots on it
    // is a month with nothing in it, which is information.
    const html = renderToStaticMarkup(
      <CalendarView calendar={{ connected: true, events: [] }} now={now} />
    )

    expect(html).toContain('September')
    expect(html).toContain('voice-calendar-strip')
    // Thirty days, each a button.
    expect(html.match(/voice-calendar-day/g)).toHaveLength(30)
    expect(html).toContain('Nothing on')
  })

  it('counts down to something starting soon', () => {
    const html = renderToStaticMarkup(
      <CalendarView
        calendar={{
          connected: true,
          events: [
            {
              id: 'a',
              title: 'Standup',
              start: '2026-09-01T09:20:00Z',
              end: '',
              location: 'Room 3',
              all_day: false
            }
          ]
        }}
        now={now}
      />
    )

    expect(html).toContain('Standup')
    expect(html).toContain('in 20 min')
    expect(html).toContain('Room 3')
  })

  it('marks an all-day event as one rather than showing midnight', () => {
    const html = renderToStaticMarkup(
      <CalendarView
        calendar={{
          connected: true,
          events: [
            { id: 'b', title: 'Holiday', start: '2026-09-01', end: '', location: '', all_day: true }
          ]
        }}
        now={now}
      />
    )

    expect(html).toContain('All day')
    expect(html).not.toContain('00:00')
  })
})
