// Timestamp and session-title helpers. Pure and deterministic.

import type { ChatMessage } from './types'

/** "14:32" (local 24-hour) for a message timestamp, or "" when not a date. */
export function formatTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const hh = String(date.getHours()).padStart(2, '0')
  const mm = String(date.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}

/** A short relative age ("now", "5m ago", "3h ago", "2d ago"). */
export function formatRelative(iso: string, now: number = Date.now()): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const minutes = Math.round((now - date.getTime()) / 60_000)
  if (minutes < 1) return 'now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

const MAX_TITLE = 42

/** Derive a session title from its first user message, or "New chat". */
export function titleFromMessages(messages: Pick<ChatMessage, 'role' | 'content'>[]): string {
  const first = messages.find((message) => message.role === 'user')
  if (!first) return 'New chat'
  const line = first.content.trim().split('\n')[0]
  if (line.length <= MAX_TITLE) return line
  return `${line.slice(0, MAX_TITLE).trimEnd()}…`
}
