import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { TelegramStatus } from '../../../../shared/runtime'
import { ChannelsPanel } from './ChannelsPanel'

const off: TelegramStatus = {
  configured: false,
  state: 'off',
  detail: 'no bot token',
  bot: null,
  owner: null,
  pairing: null,
  when_away: true,
  thread_id: ''
}

const ready: TelegramStatus = {
  ...off,
  configured: true,
  state: 'ready',
  detail: '',
  bot: { username: 'marvi_bot', name: 'Marvi', link: 'https://t.me/marvi_bot' }
}

describe('Channels > Telegram', () => {
  it('starts with BotFather and a masked token field', () => {
    const html = renderToStaticMarkup(<ChannelsPanel initial={off} />)
    expect(html).toContain('@BotFather')
    expect(html).toMatch(/aria-label="Telegram bot token"[^>]*type="password"/)
  })

  it('shows the one-time code while linking', () => {
    const pairing = {
      code: 'ABCD2345',
      link: 'https://t.me/marvi_bot?start=ABCD2345',
      expires_at: '2026-09-10T12:00:00+00:00'
    }
    const html = renderToStaticMarkup(<ChannelsPanel initial={{ ...ready, pairing }} />)
    expect(html).toContain('/start ABCD2345')
    expect(html).toContain('Open in Telegram')
    expect(html).not.toContain('aria-label="Telegram bot token"')
  })

  it('names who is linked and offers a test and an unlink', () => {
    const html = renderToStaticMarkup(
      <ChannelsPanel initial={{ ...ready, owner: { name: 'Sam', username: 'sam' } }} />
    )
    expect(html).toContain('Linked to Sam (@sam)')
    expect(html).toContain('Send a test')
    expect(html).toContain('Unlink')
    expect(html).toContain('Text me when I&#x27;m away')
  })
})
