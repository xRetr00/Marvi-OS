import { useStore } from '@nanostores/react'
import { useCallback, useEffect, useRef, useState } from 'react'

import type {
  ChatAttachment,
  ChatContext,
  ChatEntry,
  ChatPart,
  ChatThread
} from '../../../shared/runtime'
import { $agents } from '../components/agents/agents-store'
import { recordChatTurn } from '../store/session-metrics'
import { isBackground, nextJobToReport, reportedJobs } from './job-reports'
import { answerText, foldEvent } from './trace'
import { toChatMessages, type ChatMessage, type PendingConfirmation } from './types'

type Override = { provider?: string; model?: string; effort?: string }
type TurnContext = { editMessageId?: number; regenerateMessageId?: number; resumeJob?: string }

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
  /** Send text that did not come from the draft box -- a composer the SDK owns. */
  sendText: (text: string) => Promise<void>
  /** Answer an inline `clarify`/`ask_secret` card the running turn is blocked on. */
  settleAsk: (askId: string, answer: string) => Promise<void>
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
  const [reported, setReported] = useState<Set<string>>(() => new Set())
  /** Report turns already asked for this session, so one job is asked once. */
  const resuming = useRef(new Set<string>())
  const feed = useStore($agents)

  /** A page's messages, less the report notes the Gateway keeps for the model. */
  const show = useCallback((entries: ChatEntry[]): void => {
    const all = toChatMessages(entries)
    setReported(reportedJobs(all))
    setMessages(all.filter((message) => !isBackground(message)))
  }, [])

  const load = useCallback(
    async (threadId: string): Promise<void> => {
      const page = await window.marvi?.getChat(threadId)
      if (!page) return
      show(page.messages)
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
    },
    [show]
  )

  useEffect(() => {
    let disposed = false
    void window.marvi?.getChat().then((page) => {
      if (disposed || !page) return
      show(page.messages)
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
  }, [show])

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
      // A report turn has no text of the owner's: the Gateway supplies it.
      if ((!clean && !context.resumeJob) || busy) return
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
        // Marvi speaking up about finished work: no bubble from the owner.
        if (context.resumeJob) return [...current, optimisticReply]
        return [...current, optimisticUser, optimisticReply]
      })

      const startedAt = performance.now()
      let trace: ChatPart[] = []
      let firstTokenAt = 0
      let streamError = ''

      const stop = window.marvi?.onChatDelta((event) => {
        if (event.done) {
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
        if (typeof event.delta === 'string' && !firstTokenAt) firstTokenAt = performance.now()

        const next = foldEvent(trace, event)
        // Nothing this handler understands: leave the render alone rather
        // than churning the whole message list for no change.
        if (next === trace) return
        trace = next
        const parts = trace
        setMessages((current) =>
          current.map((message) =>
            message.id === replyId
              ? {
                  ...message,
                  content: answerText(parts),
                  parts,
                  meta: { ...message.meta, streaming: true }
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
        // A report that lost a race (the job is gone or already told) is
        // nothing to show; an error bubble would be noise the owner never asked for.
        if (streamError && !context.resumeJob) {
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

  // A sub-agent this conversation handed work to has finished: Marvi says what
  // came of it, as her own turn, once nothing else is running. The feed says
  // when a job ends; the Gateway's stored note says it was already reported.
  useEffect(() => {
    if (busy) return
    const next = nextJobToReport(messages, reported, feed, resuming.current)
    if (!next) return
    resuming.current.add(next)
    void runTurn('', { resumeJob: next })
  }, [busy, feed, messages, reported, runTurn])

  const send = useCallback(async () => {
    const text = draft
    if (!text.trim()) return
    setDraft('')
    await runTurn(text)
  }, [draft, runTurn])

  const sendText = useCallback(async (text: string) => runTurn(text), [runTurn])

  const settleAsk = useCallback(async (askId: string, answer: string) => {
    if (!answer.trim()) return
    const sent = await window.marvi?.settleChatAsk(askId, answer)
    if (!sent) {
      // The turn stopped waiting -- a timeout, or a window that reconnected.
      // Saying so is the whole point: the card looks answerable either way.
      setNotice('That answer arrived too late. Say it in your next message instead.')
    }
  }, [])

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
    sendText,
    settleAsk,
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
