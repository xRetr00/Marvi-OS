import { t } from '../../store/locale'
import { useEffect, useMemo, useState } from 'react'
import type { ChatMessage } from '../types'

export function ConversationMap({
  messages
}: {
  messages: readonly ChatMessage[]
}): React.JSX.Element | null {
  const turns = useMemo(() => messages.filter((message) => message.role === 'user'), [messages])
  const [active, setActive] = useState<number | null>(null)
  const [visible, setVisible] = useState<Set<number>>(new Set())

  useEffect(() => {
    const viewport = document.querySelector<HTMLElement>('.chat-log')
    if (!viewport) return
    const update = (): void => {
      const box = viewport.getBoundingClientRect()
      const seen = new Set<number>()
      let current: number | null = null
      for (const turn of turns) {
        const node = Array.from(viewport.querySelectorAll<HTMLElement>('[data-message-id]')).find(
          (item) => item.dataset.messageId === String(turn.id)
        )
        if (!node) continue
        const rect = node.getBoundingClientRect()
        if (rect.bottom > box.top && rect.top < box.bottom) seen.add(turn.id)
        if (rect.top < box.top + box.height * 0.42) current = turn.id
      }
      setVisible(seen)
      setActive(current ?? turns[0]?.id ?? null)
    }
    update()
    viewport.addEventListener('scroll', update, { passive: true })
    return () => viewport.removeEventListener('scroll', update)
  }, [turns])

  if (turns.length < 3) return null
  return (
    <nav aria-label={t('Conversation map')} className="chat-conversation-map">
      {turns.map((turn, index) => (
        <button
          aria-current={turn.id === active ? 'location' : undefined}
          aria-label={`Jump to turn ${index + 1}: ${turn.content.slice(0, 80)}`}
          className={`chat-map-tick${turn.id === active ? ' is-active' : ''}${visible.has(turn.id) ? ' is-visible' : ''}`}
          key={turn.id}
          onClick={() => {
            const viewport = document.querySelector<HTMLElement>('.chat-log')
            const node = Array.from(
              viewport?.querySelectorAll<HTMLElement>('[data-message-id]') ?? []
            ).find((item) => item.dataset.messageId === String(turn.id))
            node?.scrollIntoView({ behavior: 'smooth', block: 'start' })
          }}
          title={turn.content.slice(0, 160)}
          type="button"
        />
      ))}
    </nav>
  )
}
