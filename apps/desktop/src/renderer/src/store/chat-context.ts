import { atom } from 'nanostores'

import type { ChatContext } from '../../../shared/runtime'

export interface ChatContextStatus {
  context: ChatContext | null
  pendingFiles: number
  route?: string
}

export const $chatContextStatus = atom<ChatContextStatus>({
  context: null,
  pendingFiles: 0
})

export function setChatContextStatus(status: ChatContextStatus): void {
  $chatContextStatus.set(status)
}
