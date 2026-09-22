import { t } from '../../store/locale'
import { Tr } from '../../store/locale'
import { useCallback, useEffect, useState } from 'react'
import { BellRing, Fingerprint, Link2, Mic, Send, Unplug, Wrench } from 'lucide-react'
import TelegramLogo from '@thesvg/react/telegram'

import {
  ControlButton,
  ControlEmpty,
  ControlPage,
  ControlPill,
  ControlRow,
  ControlSection
} from '../control-surface'
import type { TelegramAction, TelegramStatus } from '../../../../shared/runtime'

const STATE_TONE = {
  off: 'neutral',
  connecting: 'warning',
  ready: 'ready',
  error: 'danger'
} as const
const STATE_LABEL = { off: 'Off', connecting: 'Connecting', ready: 'Connected', error: 'Error' }

/**
 * Capabilities > Channels: where Marvi can be reached besides this machine.
 *
 * Telegram only, today. The Gateway owns the bot; this page sets the token,
 * links the one account Marvi answers, and shows what is connected. Nothing
 * here talks to Telegram directly.
 */
export function ChannelsPanel({
  initial = null
}: {
  /** The first frame's status, before the Gateway answers. For tests. */
  initial?: TelegramStatus | null
} = {}): React.JSX.Element {
  const [status, setStatus] = useState<TelegramStatus | null>(initial)
  const [loaded, setLoaded] = useState(initial !== null)
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState<TelegramAction | ''>('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async (): Promise<void> => {
    const next = await window.marvi?.getTelegram()
    setLoaded(true)
    setStatus(next ?? null)
  }, [])

  const run = useCallback(
    async (action: TelegramAction, value?: string | boolean, done = ''): Promise<void> => {
      setBusy(action)
      setError('')
      setNotice('')
      try {
        const answer = await window.marvi?.telegram(action, value)
        if (!answer) return
        if (answer.ok) {
          setStatus(answer.status)
          if (action === 'token') setToken('')
          if (done) setNotice(done)
        } else {
          setError(answer.detail)
        }
      } finally {
        setBusy('')
      }
    },
    []
  )

  // Quick while something is about to change on its own -- a bot connecting,
  // or the phone sending the link code -- and slow otherwise.
  const waiting = status?.state === 'connecting' || Boolean(status?.pairing)
  useEffect(() => {
    let disposed = false
    const update = async (): Promise<void> => {
      if (!disposed) await load()
    }
    void update()
    const timer = setInterval(() => void update(), waiting ? 2_000 : 15_000)
    return () => {
      disposed = true
      clearInterval(timer)
    }
  }, [load, waiting])

  if (loaded && !status) {
    return (
      <ControlPage title={t('Channels')}>
        <ControlEmpty
          description={t('Marvi Gateway did not answer. Channels come back when it does.')}
          icon={Send}
          title={t('Channels unavailable')}
        />
      </ControlPage>
    )
  }

  const bot = status?.bot
  const owner = status?.owner
  const pairing = status?.pairing

  return (
    <ControlPage
      className="capabilities-page channels-page"
      description={t(
        'Talk to Marvi from your phone. She answers only you, with the same memory, tools and confirmations as here.'
      )}
      title={t('Channels')}
    >
      <ControlSection
        action={
          status ? (
            <ControlPill tone={STATE_TONE[status.state]}>
              {status.state === 'ready' && bot ? `@${bot.username}` : STATE_LABEL[status.state]}
            </ControlPill>
          ) : undefined
        }
        description={t('Long-polls Telegram from this computer. No public address, no tunnel.')}
        icon={TelegramLogo}
        title={t('Telegram')}
      >
        {status?.detail && status.state === 'error' ? (
          <p className="connector-setup-error">{status.detail}</p>
        ) : null}

        {!status?.configured ? (
          <div className="connector-setup">
            <ol className="channel-steps">
              <li>
                <Tr text={'In Telegram, open'} after />
                <strong>
                  <Tr text={'@BotFather'} />
                </strong>{' '}
                <Tr text={'and send'} before after />
                <code>/newbot</code>.
              </li>
              <li>
                <Tr text={'Pick any name and username; BotFather replies with a token.'} />
              </li>
              <li>
                <Tr
                  text={'Paste the token here. It stays on this computer with your other keys.'}
                />
              </li>
            </ol>
            <form
              className="connector-setup-form"
              onSubmit={(event) => {
                event.preventDefault()
                void run('token', token.trim())
              }}
            >
              <input
                aria-label={t('Telegram bot token')}
                autoComplete="off"
                className="control-input"
                disabled={busy === 'token'}
                onChange={(event) => setToken(event.target.value)}
                placeholder={t('123456789:AA…')}
                spellCheck={false}
                type="password"
                value={token}
              />
              <button
                className="control-button is-primary"
                disabled={busy === 'token' || !token.trim()}
              >
                {busy === 'token' ? 'Checking…' : 'Connect bot'}
              </button>
            </form>
          </div>
        ) : null}

        {status?.state === 'ready' && !owner ? (
          <ControlRow
            action={
              pairing ? undefined : (
                <ControlButton disabled={busy === 'pair'} onClick={() => void run('pair')}>
                  <Tr text={'Link my account'} />
                </ControlButton>
              )
            }
            description={
              pairing
                ? 'Scan the code with your phone’s camera and press Start in Telegram — or send the command to the bot yourself. The code works once, for ten minutes.'
                : 'Marvi answers exactly one Telegram account. Link yours with a one-time code.'
            }
            icon={Link2}
            title={pairing ? 'Waiting for your phone…' : 'Link your Telegram account'}
          >
            {pairing ? (
              <div className="channel-pairing">
                <img
                  alt={`QR code for ${pairing.link}`}
                  className="channel-qr"
                  height={168}
                  src={pairing.qr}
                  width={168}
                />
                <div className="channel-pairing-manual">
                  <span className="channel-hint">
                    <Tr text={'Or open'} after />
                    <strong>@{bot?.username}</strong>{' '}
                    <Tr text={'in Telegram and send:'} before after />
                  </span>
                  <div className="channel-pairing-command">
                    <code className="channel-code">/start {pairing.code}</code>
                    <ControlButton
                      onClick={() => {
                        const command = `/start ${pairing.code}`
                        void (async () => {
                          if (!(await window.marvi?.copyText(command))) {
                            await navigator.clipboard.writeText(command)
                          }
                          setNotice('Copied — paste it into the chat with the bot.')
                        })()
                      }}
                    >
                      <Tr text={'Copy'} />
                    </ControlButton>
                  </div>
                  {status?.desktop ? (
                    <ControlButton
                      onClick={() => void window.marvi?.openTelegramLink(pairing.link)}
                    >
                      <Tr text={'Open Telegram Desktop'} />
                    </ControlButton>
                  ) : null}
                </div>
              </div>
            ) : null}
          </ControlRow>
        ) : null}

        {owner ? (
          <ControlRow
            action={
              <>
                <ControlButton
                  disabled={busy === 'test' || status?.state !== 'ready'}
                  onClick={() => void run('test', undefined, 'Sent — check your phone.')}
                >
                  <Tr text={'Send a test'} />
                </ControlButton>
                <ControlButton
                  destructive
                  disabled={busy === 'unlink'}
                  onClick={() => void run('unlink')}
                >
                  <Tr text={'Unlink'} />
                </ControlButton>
              </>
            }
            description={t('Conversations appear in Chat as “Telegram · …” threads.')}
            icon={Link2}
            title={`Linked to ${owner.name || 'you'}${owner.username ? ` (@${owner.username})` : ''}`}
          />
        ) : null}

        {status?.configured ? (
          <>
            <ControlRow
              action={
                <button
                  aria-checked={status.when_away}
                  className={status.when_away ? 'mode-switch active' : 'mode-switch'}
                  disabled={busy === 'when-away'}
                  onClick={() => void run('when-away', !status.when_away)}
                  role="switch"
                  type="button"
                >
                  {status.when_away ? 'ON' : 'OFF'}
                </button>
              }
              description={t(
                'When Marvi has something to say out loud and nobody is in the room, she texts it instead of holding it for later. Quiet hours still mean quiet.'
              )}
              icon={BellRing}
              title={t("Text me when I'm away")}
            />
            <ControlRow
              action={
                <button
                  aria-checked={status.voice_replies !== false}
                  className={status.voice_replies !== false ? 'mode-switch active' : 'mode-switch'}
                  disabled={busy === 'voice-replies'}
                  onClick={() => void run('voice-replies', status.voice_replies === false)}
                  role="switch"
                  type="button"
                >
                  {status.voice_replies !== false ? 'ON' : 'OFF'}
                </button>
              }
              description={t(
                'Send a voice note and she answers with one too, in her own voice made on this computer — after the text, so the words never wait.'
              )}
              icon={Mic}
              title={t('Answer voice with voice')}
            />
            <ControlRow
              action={
                <ControlButton
                  disabled={busy === 'identity' || status.state !== 'ready'}
                  onClick={() => void run('identity', undefined, 'Profile updated.')}
                >
                  <Tr text={'Sync profile'} />
                </ControlButton>
              }
              description={t(
                "The bot's name, avatar, description and command menu come from Marvi. Your SOUL.md and USER.md stay private."
              )}
              icon={Fingerprint}
              title={t('Bot profile')}
            />
            <ControlRow
              description={
                <>
                  <code>telegram_send</code>{' '}
                  <Tr text={'texts you (with a workspace file if asked),'} before />{' '}
                  <code>telegram_status</code> <Tr text={'checks the link,'} before after />
                  <code>telegram_recent</code>{' '}
                  <Tr text={'reads your recent messages. Cron jobs can deliver to'} before after />
                  <em>
                    <Tr text={'Telegram (your phone)'} />
                  </em>
                  <Tr text={'. Voice notes are transcribed on this computer.'} after />
                </>
              }
              icon={Wrench}
              title={t('What Marvi can do here')}
            />
            <ControlRow
              action={
                <ControlButton
                  destructive
                  disabled={busy === 'disconnect'}
                  onClick={() => void run('disconnect')}
                >
                  <Tr text={'Disconnect bot'} />
                </ControlButton>
              }
              description={t(
                'Stops the bot and forgets its token. Your linked account is kept for when you reconnect.'
              )}
              icon={Unplug}
              title={t('Disconnect')}
            />
          </>
        ) : null}

        {error ? <p className="connector-setup-error">{error}</p> : null}
        {notice ? <p className="channel-notice">{notice}</p> : null}
      </ControlSection>
    </ControlPage>
  )
}
