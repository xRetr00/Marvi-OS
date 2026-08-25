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

  it('renders a live orb for active voice phases', () => {
    const html = renderToStaticMarkup(
      <DynamicIsland
        state={{ ...DEFAULT_ASSISTANT_STATE, phase: 'listening', caption: 'Listening' }}
      />
    )

    expect(html).toContain('island-orb')
    expect(html).toContain('Listening')
  })

  const ROOM_EVENT = {
    id: 7,
    at: '2026-08-16T03:41:00Z',
    type: 'room_presence_unverified',
    summary: 'unverified entry'
  }

  it('expands the seed for a background room event without becoming interactive', () => {
    const html = renderToStaticMarkup(
      <DynamicIsland state={{ ...DEFAULT_ASSISTANT_STATE, roomEvent: ROOM_EVENT }} />
    )

    expect(html).toContain('island-room-event')
    expect(html).toContain('unverified entry')
    expect(html).toContain('aria-live="polite"')
    // No controls: a background event must never invite or capture a click.
    expect(html).not.toContain('<button')
  })

  it('lets a live voice phase win over a background room event', () => {
    const html = renderToStaticMarkup(
      <DynamicIsland
        state={{
          ...DEFAULT_ASSISTANT_STATE,
          phase: 'listening',
          caption: 'Listening',
          roomEvent: ROOM_EVENT
        }}
      />
    )

    expect(html).not.toContain('island-room-event')
    expect(html).toContain('Listening')
  })

  it('lets a confirmation win over a background room event', () => {
    const html = renderToStaticMarkup(
      <DynamicIsland
        state={{
          ...DEFAULT_ASSISTANT_STATE,
          phase: 'confirmation',
          caption: 'Confirm action',
          roomEvent: ROOM_EVENT,
          confirmation: {
            token: 'token-1',
            action: 'Change the room light',
            detail: 'brightness=30',
            tool: 'room_set_light',
            arguments: { on: true, brightness: 30 }
          }
        }}
      />
    )

    expect(html).not.toContain('island-room-event')
    expect(html).toContain('APPROVE')
  })

  it('does not mix the global YOLO mode into a room event', () => {
    const html = renderToStaticMarkup(
      <DynamicIsland state={{ ...DEFAULT_ASSISTANT_STATE, yolo: true, roomEvent: ROOM_EVENT }} />
    )

    expect(html).toContain('island-room-event')
    expect(html).not.toContain('YOLO')
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
            detail: 'To Alex · Re: Project update',
            tool: 'email_reply',
            arguments: { to: 'Alex' }
          }
        }}
      />
    )

    expect(html).toContain('Send email reply')
    expect(html).toContain('To Alex · Re: Project update')
    expect(html).toContain('APPROVE')
    expect(html).toContain('DENY')
  })

  it('recesses into the same idle seed while YOLO is enabled', () => {
    const html = renderToStaticMarkup(
      <DynamicIsland state={{ ...DEFAULT_ASSISTANT_STATE, yolo: true }} />
    )

    expect(html).toContain('island-seed')
    expect(html).toContain('island-seed-line')
    expect(html).not.toContain('YOLO')
    expect(html).not.toContain('Say Marvi')
  })

  it('never renders mode or sensor labels in active Island content', () => {
    const html = renderToStaticMarkup(
      <DynamicIsland
        state={{
          ...DEFAULT_ASSISTANT_STATE,
          phase: 'action',
          caption: 'Turning on the light',
          yolo: true
        }}
      />
    )

    expect(html).toContain('ACTION')
    expect(html).not.toContain('YOLO')
    expect(html).not.toContain('MIC')
    expect(html).not.toContain('CAM')
  })

  it('locks both confirmation choices while a decision is resolving', () => {
    const html = renderToStaticMarkup(
      <DynamicIsland
        confirmationPending
        state={{
          ...DEFAULT_ASSISTANT_STATE,
          phase: 'confirmation',
          confirmation: {
            token: 'token-1',
            action: 'Send email reply',
            detail: 'To Alex',
            tool: 'email_reply',
            arguments: { to: 'Alex' }
          }
        }}
      />
    )

    expect(html.match(/disabled=""/g)).toHaveLength(2)
    expect(html).toContain('WAIT…')
  })
})
