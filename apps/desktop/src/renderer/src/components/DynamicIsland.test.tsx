import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { DynamicIsland } from './DynamicIsland'
import {
  ANNOUNCEMENT_GLANCE_MS,
  ISLAND_AUTO_EXPAND_MS,
  ISLAND_ENTER_SECONDS,
  ISLAND_LINE_CLIP,
  ISLAND_OPEN_CLIP,
  ISLAND_EXIT_SECONDS,
  ISLAND_REDUCED_MOTION_SECONDS,
  announcementSourceLabel,
  islandDisplayState,
  islandHasOrb,
  islandInteractionMode,
  islandPresentationKey
} from './island-presentation'
import { DEFAULT_ASSISTANT_STATE } from '../../../shared/runtime'

describe('DynamicIsland', () => {
  const ANNOUNCEMENT = {
    id: 'announcement-1',
    text: 'The reminder is due.',
    source: 'schedule:reminder',
    at: '2026-09-07T06:00:00Z',
    active: true,
    expiresAt: null
  }

  it('uses stable presentation keys and a faster exit than entrance', () => {
    expect(islandPresentationKey(DEFAULT_ASSISTANT_STATE)).toBe('ready')
    expect(
      islandPresentationKey({ ...DEFAULT_ASSISTANT_STATE, roomEvent: { ...ROOM_EVENT, id: 12 } })
    ).toBe('room-event:12')
    expect(ISLAND_EXIT_SECONDS).toBeLessThan(ISLAND_ENTER_SECONDS)
    expect(ISLAND_REDUCED_MOTION_SECONDS).toBeLessThan(ISLAND_EXIT_SECONDS)
    expect(ISLAND_AUTO_EXPAND_MS).toBe(1800)
    expect(ISLAND_LINE_CLIP).toContain('50% - 17px')
    expect(ISLAND_LINE_CLIP).toContain('100% - 2px')
    expect(ISLAND_OPEN_CLIP).toBe('inset(0px 0px 0px round 22px)')
    expect(ANNOUNCEMENT_GLANCE_MS).toBe(10_000)
    expect(
      islandPresentationKey({
        ...DEFAULT_ASSISTANT_STATE,
        phase: 'announcing',
        announcement: ANNOUNCEMENT
      })
    ).toBe('announcement:announcement-1:active')
  })

  it('lets retained announcements reclaim idle, but never live, voice state', () => {
    const retained = { ...ANNOUNCEMENT, active: false }
    expect(islandDisplayState({ ...DEFAULT_ASSISTANT_STATE, announcement: retained }).phase).toBe(
      'announcing'
    )
    expect(
      islandDisplayState({
        ...DEFAULT_ASSISTANT_STATE,
        phase: 'listening',
        announcement: retained
      }).phase
    ).toBe('listening')
    expect(announcementSourceLabel('accounts:gmail')).toBe('MAIL')
    expect(announcementSourceLabel('schedule:reminder')).toBe('REMINDER')
  })

  it('makes the exact announcement primary while audio is on air', () => {
    const html = renderToStaticMarkup(
      <DynamicIsland
        state={{
          ...DEFAULT_ASSISTANT_STATE,
          phase: 'announcing',
          announcement: ANNOUNCEMENT
        }}
      />
    )

    expect(html).toContain('data-announcement-active="true"')
    expect(html).toContain('REMINDER · NOW')
    expect(html).toContain('<strong>The reminder is due.</strong>')
    expect(html).not.toContain('Marvi has something')
  })

  it('keeps a held announcement accessible when it collapses to its orb', () => {
    const html = renderToStaticMarkup(
      <DynamicIsland
        expanded={false}
        state={{
          ...DEFAULT_ASSISTANT_STATE,
          phase: 'announcing',
          announcement: { ...ANNOUNCEMENT, active: false }
        }}
      />
    )

    expect(html).toContain('is-collapsed')
    expect(html).toContain('aria-label="REMINDER · NOW: The reminder is due."')
    expect(html).not.toContain('<strong>The reminder is due.</strong>')
  })

  it('captures hover without focus only for states that have an orb', () => {
    expect(islandHasOrb(DEFAULT_ASSISTANT_STATE)).toBe(false)
    expect(islandInteractionMode(DEFAULT_ASSISTANT_STATE)).toBe('passive')
    expect(
      islandInteractionMode({
        ...DEFAULT_ASSISTANT_STATE,
        phase: 'listening',
        caption: 'Listening'
      })
    ).toBe('hover')
    expect(islandInteractionMode({ ...DEFAULT_ASSISTANT_STATE, roomEvent: ROOM_EVENT })).toBe(
      'hover'
    )
  })

  it('rests in a line-only idle seed', () => {
    const html = renderToStaticMarkup(<DynamicIsland state={DEFAULT_ASSISTANT_STATE} />)

    expect(html).toContain('island-seed')
    expect(html).toContain('island-seed-line')
    expect(html).toContain('Marvi OS ready')
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
    expect(html).toContain('LISTEN')
  })

  it('collapses to an orb capsule with a concise visible and accessible status', () => {
    const html = renderToStaticMarkup(
      <DynamicIsland
        expanded={false}
        state={{ ...DEFAULT_ASSISTANT_STATE, phase: 'speaking', caption: 'Speaking' }}
      />
    )

    expect(html).toContain('is-collapsed')
    expect(html).toContain('data-expanded="false"')
    expect(html).toContain('aria-label="SPEAK: Speaking"')
    expect(html).toContain('island-orb')
    expect(html).not.toContain('<strong>Speaking</strong>')
    expect(html).toContain('island-compact-label')
    expect(html).toContain('>SPEAK</small>')
  })

  it('presents a persistent outage as a quiet current state', () => {
    const html = renderToStaticMarkup(
      <DynamicIsland
        state={{
          ...DEFAULT_ASSISTANT_STATE,
          phase: 'error',
          caption: 'Gateway unavailable',
          detail: 'Retrying locally'
        }}
      />
    )

    expect(html).toContain('OFFLINE')
    expect(html).toContain('Gateway unavailable')
    expect(html).toContain('Retrying locally')
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

  it('uses the same idle line while YOLO is enabled', () => {
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

    expect(html).toContain('WORKING')
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
