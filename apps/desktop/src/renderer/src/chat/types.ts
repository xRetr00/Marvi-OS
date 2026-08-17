// Chat view-model types and small pure mappings from the gateway's wire shape
// to what the UI renders. Kept free of React so they are trivially testable.

import type { ChatEntry } from '../../../shared/runtime'

export type ChatRole = 'user' | 'assistant' | 'tool' | 'error'

export interface ChatMessage {
  id: number
  at: string
  role: ChatRole
  content: string
  meta: Record<string, unknown>
}

/** Roles the gateway actually persists; anything else renders as an error. */
const KNOWN_ROLES: ReadonlySet<string> = new Set(['user', 'assistant', 'tool'])

export function toChatMessage(entry: ChatEntry): ChatMessage {
  return {
    id: entry.id,
    at: entry.at,
    role: KNOWN_ROLES.has(entry.role) ? (entry.role as ChatRole) : 'error',
    content: entry.content,
    meta: entry.meta ?? {}
  }
}

export function toChatMessages(entries: ChatEntry[]): ChatMessage[] {
  return entries.map(toChatMessage)
}

/** Read a string (or number) out of a message's metadata, if present. */
export function metaValue(meta: Record<string, unknown>, key: string): string {
  const value = meta[key]
  if (typeof value === 'string') return value
  if (typeof value === 'number') return String(value)
  return ''
}

export interface PendingConfirmation {
  tool: string
  token: string
}
