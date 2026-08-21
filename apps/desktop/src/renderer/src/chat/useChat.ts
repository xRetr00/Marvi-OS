// State and actions for the chat surface. The only React in this module is the
// hook itself; the components stay presentational and easy to restyle.

import { useCallback, useEffect, useState } from 'react'

import { toChatMessages, type ChatMessage, type PendingConfirmation } from './types'
import { recordChatTurn } from '../store/session-metrics'

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
  override: { provider?: string; model?: string; effort?: string }
  setOverride: (next: { provider?: string; model?: string; effort?: string }) => void
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
  const [override, setOverride] = useState<{ provider?: string; model?: string; effort?: string }>(
    {}
  )
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
    const userId = -Date.now()
    const replyId = userId - 1
    setMessages((current) => [
      ...current,
      { id: userId, at: new Date().toISOString(), role: 'user', content: text, meta: {} },
      // The reply exists before it has any words in it, so the tokens have
      // somewhere to land as they arrive.
      {
        id: replyId,
        at: new Date().toISOString(),
        role: 'assistant',
        content: '',
        meta: { streaming: true }
      }
    ])

    const startedAt = performance.now()
    let answer = ''
    let reasoning = ''
    let firstTokenAt = 0

    const stop = window.marvi?.onChatDelta((event) => {
      if (typeof event.delta === 'string') {
        if (!firstTokenAt) firstTokenAt = performance.now()
        answer += event.delta
      } else if (typeof event.reasoning === 'string') {
        // Kept apart from the answer. It is not what Marvi said.
        reasoning += event.reasoning
      } else if (typeof event.tool === 'string') {
        setMessages((current) =>
          current.map((message) =>
            message.id === replyId
              ? { ...message, meta: { ...message.meta, tool: String(event.tool) } }
              : message
          )
        )
        return
      } else if (event.done) {
        return
      }

      setMessages((current) =>
        current.map((message) =>
          message.id === replyId
            ? { ...message, content: answer, meta: { ...message.meta, reasoning, streaming: true } }
            : message
        )
      )
    })

    try {
      await window.marvi?.streamChat(text, override)
      if (firstTokenAt) recordChatTurn(firstTokenAt - startedAt)
      // The transcript is authoritative once the turn is over: it carries the
      // provider, the token count, and anything a tool wrote.
      const page = await window.marvi?.getChat()
      if (page) setMessages(toChatMessages(page.messages))
    } finally {
      stop?.()
      setBusy(false)
    }
  }, [draft, busy, override])

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
