// State and actions for the chat surface. The only React in this module is the
// hook itself; the components stay presentational and easy to restyle.

import { useCallback, useEffect, useState } from 'react'

import { toChatMessages, type ChatMessage, type PendingConfirmation } from './types'

export interface UseChat {
  messages: ChatMessage[]
  busy: boolean
  available: boolean
  draft: string
  pending: PendingConfirmation | null
  setDraft: (next: string) => void
  send: () => Promise<void>
  clear: () => Promise<void>
  resolve: (decision: 'approve' | 'deny') => Promise<void>
  /** The model this session picked, if any. Sent per turn, stored nowhere. */
  override: { provider?: string; model?: string }
  setOverride: (next: { provider?: string; model?: string }) => void
}

export function useChat(): UseChat {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [busy, setBusy] = useState(false)
  const [available, setAvailable] = useState(true)
  const [draft, setDraft] = useState('')
  /**
   * A model chosen for this session only.
   *
   * Held in component state on purpose: it dies with the window, is written
   * nowhere, and is sent per turn. A picker that quietly rewrote the
   * configured default would make whatever anyone last experimented with the
   * new model for voice, mind and vision as well.
   */
  const [override, setOverride] = useState<{ provider?: string; model?: string }>({})
  const [pending, setPending] = useState<PendingConfirmation | null>(null)

  useEffect(() => {
    let disposed = false
    void window.marvi?.getChat().then((page) => {
      if (disposed || !page) return
      setMessages(toChatMessages(page.messages))
      setAvailable(page.available)
    })
    return () => {
      disposed = true
    }
  }, [])

  const send = useCallback(async (): Promise<void> => {
    const text = draft.trim()
    if (!text || busy) return
    setDraft('')
    setBusy(true)
    // Echo the user's line immediately; waiting for the round trip makes the
    // window feel frozen.
    setMessages((current) => [
      ...current,
      { id: -Date.now(), at: new Date().toISOString(), role: 'user', content: text, meta: {} }
    ])
    try {
      const reply = await window.marvi?.sendChat(text, override)
      const page = await window.marvi?.getChat()
      if (page) setMessages(toChatMessages(page.messages))
      const confirmation = reply?.pending_confirmation
      setPending(
        confirmation
          ? {
              tool: String(confirmation.tool ?? ''),
              token: String(confirmation.token ?? '')
            }
          : null
      )
      if (reply?.error) {
        setMessages((current) => [
          ...current,
          {
            id: -Date.now(),
            at: new Date().toISOString(),
            role: 'error',
            content: reply.error,
            meta: {}
          }
        ])
      }
    } finally {
      setBusy(false)
    }
  }, [draft, busy])

  const resolve = useCallback(
    async (decision: 'approve' | 'deny'): Promise<void> => {
      if (!pending) return
      await window.marvi?.resolveConfirmation(pending.token, decision)
      setPending(null)
    },
    [pending]
  )

  const clear = useCallback(async (): Promise<void> => {
    await window.marvi?.clearChat()
    setMessages([])
    setPending(null)
  }, [])

  return {
    messages,
    busy,
    available,
    draft,
    pending,
    setDraft,
    send,
    clear,
    resolve,
    override,
    setOverride
  }
}
