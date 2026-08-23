import { beforeEach, describe, expect, it, vi } from 'vitest'

const connect = vi.hoisted(() => vi.fn())

vi.mock('../lib/livekit-room', () => ({ connectVoiceRoom: connect, expectDisconnect: vi.fn() }))
vi.mock('./voice-state', () => ({ cycleVoicePhase: vi.fn() }))

/** Just enough Room to be started, stopped, and to hang up on its own. */
function fakeRoom(): {
  disconnect: ReturnType<typeof vi.fn>
  once: ReturnType<typeof vi.fn>
  remoteParticipants: Map<string, unknown>
  localParticipant: { performRpc: ReturnType<typeof vi.fn> }
} {
  const handlers: Record<string, () => void> = {}
  return {
    disconnect: vi.fn(async () => {}),
    remoteParticipants: new Map([
      ['agent', { identity: 'agent', attributes: { 'lk.agent.state': 'listening' } }]
    ]),
    localParticipant: { performRpc: vi.fn(async () => '{"ok":true}') },
    once: vi.fn((event: string, handler: () => void) => {
      handlers[event] = handler
      return undefined
    }),
    // Exposed for the test that simulates the far side going away.
    ...({ fire: (event: string) => handlers[event]?.() } as Record<string, unknown>)
  } as never
}

describe('the voice session', () => {
  beforeEach(async () => {
    vi.resetModules()
    connect.mockReset()
  })

  it('is off before anything starts it', async () => {
    const { $voiceLink } = await import('./voice-session')

    expect($voiceLink.get()).toBe('off')
  })

  it('goes live once the room connects', async () => {
    connect.mockResolvedValue(fakeRoom())
    const { $voiceLink, startVoice } = await import('./voice-session')

    await startVoice()

    expect($voiceLink.get()).toBe('live')
  })

  it('can be ended, which is the whole point', async () => {
    // The room used to be held in a mount effect's closure, so the only way to
    // stop Marvi listening was to quit the app.
    const room = fakeRoom()
    connect.mockResolvedValue(room)
    const { $voiceLink, startVoice, stopVoice } = await import('./voice-session')

    await startVoice()
    await stopVoice()

    expect(room.disconnect).toHaveBeenCalled()
    expect($voiceLink.get()).toBe('off')
  })

  it('does not open a second room when started twice', async () => {
    connect.mockResolvedValue(fakeRoom())
    const { startVoice } = await import('./voice-session')

    await Promise.all([startVoice(), startVoice()])

    expect(connect).toHaveBeenCalledTimes(1)
  })

  it('uses an audio-only room and the agent RPC for read aloud', async () => {
    const target = fakeRoom()
    connect.mockResolvedValue(target)
    const { readAloudWithMarvi } = await import('./voice-session')

    await readAloudWithMarvi('A settled Chat response.')

    expect(connect).toHaveBeenCalledWith({ microphone: false })
    expect(target.localParticipant.performRpc).toHaveBeenCalledWith(
      expect.objectContaining({
        destinationIdentity: 'agent',
        method: 'marvi.read_aloud',
        payload: JSON.stringify({ text: 'A settled Chat response.' })
      })
    )
    expect(target.disconnect).toHaveBeenCalled()
  })

  it('falls back to off when the room refuses to connect', async () => {
    connect.mockRejectedValue(new Error('no gateway'))
    const { $voiceLink, startVoice } = await import('./voice-session')

    await startVoice()

    expect($voiceLink.get()).toBe('off')
  })

  it('can be started again after a failure', async () => {
    connect.mockRejectedValueOnce(new Error('no gateway')).mockResolvedValueOnce(fakeRoom())
    const { $voiceLink, startVoice } = await import('./voice-session')

    await startVoice()
    await startVoice()

    expect($voiceLink.get()).toBe('live')
  })

  it('reports off when the far side hangs up', async () => {
    // Otherwise the button would offer to End something already ended.
    const room = fakeRoom() as unknown as { fire: (event: string) => void }
    connect.mockResolvedValue(room)
    const { $voiceLink, startVoice } = await import('./voice-session')

    await startVoice()
    room.fire('disconnected')

    expect($voiceLink.get()).toBe('off')
  })
})

describe('a failure to join', () => {
  beforeEach(async () => {
    vi.resetModules()
    connect.mockReset()
  })

  it('keeps the reason instead of a canned caption', async () => {
    // It used to be swallowed -- `.catch(() => cycleVoicePhase('error'))` --
    // and the page showed that phase's fixed text, "Gateway unavailable", for
    // every cause including a Gateway that was fine. A refused microphone and
    // an unreachable server read identically.
    connect.mockRejectedValue(new Error('The microphone could not be opened: NotAllowedError'))
    const { $voiceError, startVoice } = await import('./voice-session')

    await startVoice()

    expect($voiceError.get()).toContain('microphone')
    expect($voiceError.get()).toContain('NotAllowedError')
  })

  it('clears the reason when a later attempt works', async () => {
    connect.mockRejectedValueOnce(new Error('no route to host')).mockResolvedValueOnce(fakeRoom())
    const { $voiceError, startVoice } = await import('./voice-session')

    await startVoice()
    expect($voiceError.get()).not.toBe('')

    await startVoice()
    expect($voiceError.get()).toBe('')
  })
})
