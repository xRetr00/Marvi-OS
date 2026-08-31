import { useCallback, useEffect, useState } from 'react'

import type {
  ChatAttachment,
  ChatContext,
  ChatThread,
  ChatWidgetPart
} from '../../../shared/runtime'
import { recordChatTurn } from '../store/session-metrics'
import { toChatMessages, type ChatMessage, type PendingConfirmation } from './types'

type Override = { provider?: string; model?: string; effort?: string }
type TurnContext = { editMessageId?: number; regenerateMessageId?: number }

export interface UseChat {
  messages: ChatMessage[]
  threads: ChatThread[]
  activeThreadId: string
  attachments: ChatAttachment[]
  context: ChatContext | null
  notice: string
  busy: boolean
  available: boolean
  draft: string
  pending: PendingConfirmation | null
  override: Override
  setDraft: (next: string) => void
  setOverride: (next: Override) => void
  send: () => Promise<void>
  edit: (messageId: number, content: string) => Promise<void>
  regenerate: (messageId: number) => Promise<void>
  clear: () => Promise<void>
  createThread: () => Promise<void>
  selectThread: (id: string) => Promise<void>
  renameThread: (id: string, title: string) => Promise<void>
  archiveThread: (id: string) => Promise<void>
  deleteThread: (id: string) => Promise<void>
  addAttachments: (files: FileList | File[]) => Promise<void>
  removeAttachment: (id: string) => Promise<void>
  resolve: (decision: 'approve' | 'deny') => Promise<void>
  cancel: () => Promise<void>
}

export function useChat(): UseChat {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [threads, setThreads] = useState<ChatThread[]>([])
  const [activeThreadId, setActiveThreadId] = useState('default')
  const [attachments, setAttachments] = useState<ChatAttachment[]>([])
  const [context, setContext] = useState<ChatContext | null>(null)
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [available, setAvailable] = useState(true)
  const [draft, setDraft] = useState('')
  const [override, setOverrideState] = useState<Override>({})
  const [pending, setPending] = useState<PendingConfirmation | null>(null)

  const load = useCallback(async (threadId: string): Promise<void> => {
    const page = await window.marvi?.getChat(threadId)
    if (!page) return
    setMessages(toChatMessages(page.messages))
    setThreads(page.threads)
    setActiveThreadId(page.active_thread)
    const active = page.threads.find((thread) => thread.id === page.active_thread)
    setOverrideState(
      active
        ? {
            provider: active.selected_provider || undefined,
            model: active.selected_model || undefined,
            effort: active.selected_effort || undefined
          }
        : {}
    )
    setAvailable(page.available)
    setContext(page.context)
    setAttachments([])
  }, [])

  useEffect(() => {
    let disposed = false
    void window.marvi?.getChat().then((page) => {
      if (disposed || !page) return
      setMessages(toChatMessages(page.messages))
      setThreads(page.threads)
      setActiveThreadId(page.active_thread)
      const active = page.threads.find((thread) => thread.id === page.active_thread)
      setOverrideState(
        active
          ? {
              provider: active.selected_provider || undefined,
              model: active.selected_model || undefined,
              effort: active.selected_effort || undefined
            }
          : {}
      )
      setAvailable(page.available)
      setContext(page.context)
    })
    return () => {
      disposed = true
    }
  }, [])

  const setOverride = useCallback(
    (next: Override): void => {
      setOverrideState(next)
      void window.marvi?.setChatThreadModel(activeThreadId, next).then((thread) => {
        if (!thread) return
        setThreads((current) => current.map((item) => (item.id === thread.id ? thread : item)))
      })
    },
    [activeThreadId]
  )

  const runTurn = useCallback(
    async (text: string, context: TurnContext = {}): Promise<void> => {
      const clean = text.trim()
      if (!clean || busy) return
      setBusy(true)
      setPending(null)
      setNotice('')

      const userId = -Date.now()
      const replyId = userId - 1
      const optimisticUser: ChatMessage = {
        id: userId,
        at: new Date().toISOString(),
        role: 'user',
        content: clean,
        meta: {},
        threadId: activeThreadId,
        parentId: null,
        branchId: 'pending',
        parts: [
          { type: 'text', text: clean },
          ...attachments.map((attachment) => ({
            type: 'attachment' as const,
            attachment_id: attachment.id,
            name: attachment.name,
            media_type: attachment.media_type,
            size: attachment.size
          }))
        ],
        attachments
      }
      const optimisticReply: ChatMessage = {
        id: replyId,
        at: new Date().toISOString(),
        role: 'assistant',
        content: '',
        meta: { streaming: true },
        threadId: activeThreadId,
        parentId: userId,
        branchId: 'pending',
        parts: [],
        attachments: []
      }

      setMessages((current) => {
        if (context.editMessageId !== undefined) {
          const index = current.findIndex((message) => message.id === context.editMessageId)
          return [...current.slice(0, Math.max(0, index)), optimisticUser, optimisticReply]
        }
        if (context.regenerateMessageId !== undefined) {
          const index = current.findIndex((message) => message.id === context.regenerateMessageId)
          const cut = index >= 0 ? index : current.length
          return [...current.slice(0, cut), optimisticReply]
        }
        return [...current, optimisticUser, optimisticReply]
      })

      const startedAt = performance.now()
      let answer = ''
      let reasoning = ''
      let firstTokenAt = 0
      let streamError = ''

      const stop = window.marvi?.onChatDelta((event) => {
        if (typeof event.delta === 'string') {
          if (!firstTokenAt) firstTokenAt = performance.now()
          answer += event.delta
        } else if (typeof event.reasoning === 'string') {
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
        } else if (event.widget && typeof event.widget === 'object') {
          const widget = event.widget as ChatWidgetPart
          setMessages((current) =>
            current.map((message) =>
              message.id === replyId
                ? {
                    ...message,
                    parts: [...message.parts.filter((part) => part.type !== 'text'), widget]
                  }
                : message
            )
          )
          return
        } else if (event.done) {
          if (typeof event.error === 'string') streamError = event.error
          const confirmation = event.pending_confirmation
          if (confirmation && typeof confirmation === 'object') {
            const value = confirmation as Record<string, unknown>
            if (typeof value.tool === 'string' && typeof value.token === 'string') {
              setPending({ tool: value.tool, token: value.token })
            }
          }
          return
        }
        setMessages((current) =>
          current.map((message) =>
            message.id === replyId
              ? {
                  ...message,
                  content: answer,
                  parts: [
                    { type: 'text', text: answer },
                    ...message.parts.filter((part) => part.type !== 'text')
                  ],
                  meta: { ...message.meta, reasoning, streaming: true }
                }
              : message
          )
        )
      })

      try {
        await window.marvi?.streamChat(clean, override, {
          threadId: activeThreadId,
          attachmentIds: attachments.map((attachment) => attachment.id),
          ...context
        })
        if (firstTokenAt) recordChatTurn(firstTokenAt - startedAt)
        await load(activeThreadId)
        if (streamError) {
          setMessages((current) => [
            ...current,
            {
              id: replyId - 1,
              at: new Date().toISOString(),
              role: 'error',
              content: streamError,
              meta: {},
              threadId: activeThreadId,
              parentId: null,
              branchId: 'error',
              parts: [{ type: 'text', text: streamError }],
              attachments: []
            }
          ])
        }
      } finally {
        stop?.()
        setAttachments([])
        setBusy(false)
      }
    },
    [activeThreadId, attachments, busy, load, override]
  )

  const send = useCallback(async () => {
    const text = draft
    if (!text.trim()) return
    setDraft('')
    await runTurn(text)
  }, [draft, runTurn])

  const edit = useCallback(
    async (messageId: number, content: string) => runTurn(content, { editMessageId: messageId }),
    [runTurn]
  )

  const regenerate = useCallback(
    async (messageId: number) => {
      const message = messages.find((entry) => entry.id === messageId)
      const user = message ? userAncestor(messages, message) : undefined
      if (user) await runTurn(user.content, { regenerateMessageId: messageId })
    },
    [messages, runTurn]
  )

  const createThread = useCallback(async () => {
    const thread = await window.marvi?.createChatThread()
    if (thread) await load(thread.id)
  }, [load])

  const selectThread = useCallback(async (id: string) => load(id), [load])
  const renameThread = useCallback(
    async (id: string, title: string) => {
      await window.marvi?.updateChatThread(id, { title })
      await load(activeThreadId)
    },
    [activeThreadId, load]
  )
  const archiveThread = useCallback(
    async (id: string) => {
      await window.marvi?.updateChatThread(id, { archived: true })
      const next = threads.find((thread) => thread.id !== id)
      if (next) await load(next.id)
      else await createThread()
    },
    [createThread, load, threads]
  )
  const deleteThread = useCallback(
    async (id: string) => {
      const removed = await window.marvi?.deleteChatThread(id)
      if (!removed) {
        setNotice('The conversation could not be deleted. Try again when the Gateway is ready.')
        return
      }
      const remaining = (await window.marvi?.getChatThreads(false)) ?? []
      const next =
        id === activeThreadId
          ? remaining[0]
          : (remaining.find((thread) => thread.id === activeThreadId) ?? remaining[0])
      setNotice('')
      if (next) await load(next.id)
      else await createThread()
    },
    [activeThreadId, createThread, load]
  )

  const addAttachments = useCallback(
    async (files: FileList | File[]) => {
      for (const file of Array.from(files)) {
        try {
          const data = arrayBufferToBase64(await file.arrayBuffer())
          const attachment = await window.marvi?.uploadChatAttachment({
            threadId: activeThreadId,
            name: file.name,
            // An empty browser MIME lets the Gateway infer trusted extensions
            // such as .md/.docx. Forcing octet-stream made those valid files
            // look unsupported on Windows.
            mediaType: file.type,
            data
          })
          if (!attachment) throw new Error('The Gateway did not accept the file.')
          setAttachments((current) => [...current, attachment])
          setNotice('')
        } catch (error) {
          setNotice(`${file.name}: ${error instanceof Error ? error.message : 'Upload failed.'}`)
        }
      }
    },
    [activeThreadId]
  )

  const removeAttachment = useCallback(async (id: string) => {
    await window.marvi?.removeChatAttachment(id)
    setAttachments((current) => current.filter((attachment) => attachment.id !== id))
  }, [])

  const cancel = useCallback(async () => {
    await window.marvi?.cancelChat()
  }, [])
  useEffect(() => () => void window.marvi?.cancelChat(), [])

  const resolve = useCallback(
    async (decision: 'approve' | 'deny') => {
      if (!pending) return
      await window.marvi?.resolveConfirmation(pending.token, decision)
      setPending(null)
    },
    [pending]
  )

  const clear = useCallback(async () => {
    await window.marvi?.clearChat(activeThreadId)
    await load(activeThreadId)
    setPending(null)
  }, [activeThreadId, load])

  return {
    messages,
    threads,
    activeThreadId,
    attachments,
    context,
    notice,
    busy,
    available,
    draft,
    pending,
    override,
    setDraft,
    setOverride,
    send,
    edit,
    regenerate,
    clear,
    createThread,
    selectThread,
    renameThread,
    archiveThread,
    deleteThread,
    addAttachments,
    removeAttachment,
    resolve,
    cancel
  }
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000))
  }
  return btoa(binary)
}

export function userAncestor(
  messages: readonly ChatMessage[],
  message: ChatMessage
): ChatMessage | undefined {
  let current: ChatMessage | undefined = message
  const visited = new Set<number>()
  while (current && !visited.has(current.id)) {
    if (current.role === 'user') return current
    visited.add(current.id)
    current = messages.find((entry) => entry.id === current?.parentId)
  }
  return undefined
}
