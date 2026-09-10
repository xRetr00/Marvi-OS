/**
 * `useChat` as an assistant-ui runtime.
 *
 * The store stays exactly where it was. This is an adapter, not a rewrite:
 * every handler below forwards to a `useChat` method that already existed and
 * already worked, so the SDK gets its contract and the IPC layer never learns
 * that anything changed.
 *
 * ## Why the external-store runtime and not a local one
 *
 * A local runtime owns the messages and asks an adapter to produce replies.
 * Marvi's messages live in the Gateway's SQLite, are branched there, and are
 * reloaded from there after every turn -- so the window is a view of a store
 * it does not own. `useExternalStoreRuntime` is the one that says so.
 */

import { useMemo } from 'react'
import type { AppendMessage, ExternalStoreAdapter } from '@assistant-ui/react'
import { useExternalStoreRuntime } from '@assistant-ui/react'
import type { AssistantRuntime } from '@assistant-ui/react'

import type { UseChat } from '../useChat'
import type { ChatMessage } from '../types'
import { convertMessage, isRenderable } from './convert'

/** Pull the plain text out of whatever the composer produced.
 *
 * Attachments travel their own path -- they are uploaded before send and
 * referenced by id -- so the text parts are the whole of the message here.
 */
export function appendedText(message: AppendMessage): string {
  return message.content
    .filter((part): part is { type: 'text'; text: string } => part.type === 'text')
    .map((part) => part.text)
    .join('\n')
    .trim()
}

/** The stored message an assistant-ui id refers to.
 *
 * Ids are stringified row ids, and optimistic rows use negative ones, so this
 * is a lookup rather than a parse: a `NaN` from a synthetic id must not match
 * a real row.
 */
export function messageById(
  messages: readonly ChatMessage[],
  id: string | null
): ChatMessage | undefined {
  if (id === null) return undefined
  return messages.find((message) => String(message.id) === id)
}

export function useMarviRuntime(chat: UseChat): AssistantRuntime {
  const visible = useMemo(() => chat.messages.filter(isRenderable), [chat.messages])

  const adapter = useMemo<ExternalStoreAdapter<ChatMessage>>(
    () => ({
      messages: visible,
      isRunning: chat.busy,
      isDisabled: !chat.available,
      convertMessage,

      onNew: async (message) => {
        const text = appendedText(message)
        if (text) await chat.sendText(text)
      },

      onEdit: async (message) => {
        const text = appendedText(message)
        // `parentId` is the message *before* the one being replaced, which is
        // how assistant-ui addresses an edit. Marvi forks on the user message
        // itself, so the edited row is the one after the parent.
        const index = chat.messages.findIndex(
          (entry) => String(entry.id) === String(message.parentId)
        )
        const target = chat.messages[index + 1] ?? chat.messages[index]
        if (text && target) await chat.edit(target.id, text)
      },

      onReload: async (parentId) => {
        const parent = messageById(chat.messages, parentId)
        // Regenerating means replacing the reply that followed the parent.
        const index = parent ? chat.messages.indexOf(parent) : -1
        const reply = chat.messages
          .slice(index + 1)
          .find((entry) => entry.role === 'assistant' || entry.role === 'error')
        if (reply) await chat.regenerate(reply.id)
      },

      onCancel: async () => {
        await chat.cancel()
      },

      onAddToolResult: async ({ toolCallId, result }) => {
        // The only client-answered tools are the inline question cards, and
        // their result is the text the user chose or typed.
        await chat.settleAsk(toolCallId, String((result as { answer?: string })?.answer ?? ''))
      },

      adapters: {
        threadList: {
          threadId: chat.activeThreadId,
          threads: chat.threads.map((thread) => ({
            status: 'regular' as const,
            id: thread.id,
            title: thread.title
          })),
          onSwitchToThread: (id) => chat.selectThread(id),
          onSwitchToNewThread: () => chat.createThread(),
          onRename: (id, title) => chat.renameThread(id, title),
          onArchive: (id) => chat.archiveThread(id),
          onDelete: (id) => chat.deleteThread(id)
        }
      }
    }),
    [chat, visible]
  )

  return useExternalStoreRuntime(adapter)
}
