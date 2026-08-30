import { useMemo, useState } from 'react'
import {
  BrainCircuit,
  CalendarDays,
  ChevronDown,
  FileText,
  Globe2,
  Home,
  Mail,
  Search,
  TerminalSquare,
  Wrench,
  type LucideIcon
} from 'lucide-react'

import { Markdown } from '../MarkdownView'
import { metaValue, type ChatMessage } from '../types'

interface ToolView {
  message: ChatMessage
  name: string
  category: string
  categoryLabel: string
  arguments: Record<string, unknown> | null
}

const CATEGORY_ICONS: Readonly<Record<string, LucideIcon>> = {
  calendar: CalendarDays,
  email: Mail,
  file: FileText,
  memory: BrainCircuit,
  room: Home,
  search: Search,
  terminal: TerminalSquare,
  web: Globe2
}

function words(value: string): string {
  return value
    .replaceAll(/[_-]+/g, ' ')
    .trim()
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function toolLabel(value: string): string {
  return value
    .replaceAll(/[_-]+/g, ' ')
    .trim()
    .replace(/^\w/, (letter) => letter.toUpperCase())
}

function categoryOf(name: string): string {
  const lower = name.toLowerCase()
  if (/mail|gmail/.test(lower)) return 'email'
  if (/calendar|schedule/.test(lower)) return 'calendar'
  if (/search/.test(lower)) return 'search'
  if (/web|fetch|browser/.test(lower)) return 'web'
  if (/memory|recall|remember/.test(lower)) return 'memory'
  if (/room|light|device|presence/.test(lower)) return 'room'
  if (/file|document|attachment/.test(lower)) return 'file'
  if (/terminal|command|process|shell/.test(lower)) return 'terminal'
  return name.split(/[_-]/)[0] || 'general'
}

function toolView(message: ChatMessage): ToolView {
  const name = metaValue(message.meta, 'tool') || 'tool'
  const category = categoryOf(name)
  const rawArguments = message.meta.arguments
  return {
    message,
    name,
    category,
    categoryLabel: words(category),
    arguments:
      rawArguments && typeof rawArguments === 'object' && !Array.isArray(rawArguments)
        ? (rawArguments as Record<string, unknown>)
        : null
  }
}

function ToolIcon({ category }: { category: string }): React.JSX.Element {
  const Icon = CATEGORY_ICONS[category] ?? Wrench
  return (
    <span className="chat-tool-icon" data-category={category}>
      <Icon aria-hidden="true" size={15} strokeWidth={1.6} />
    </span>
  )
}

export function ToolCallsSection({
  messages
}: {
  messages: ChatMessage[]
}): React.JSX.Element | null {
  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const tools = useMemo(() => messages.map(toolView), [messages])
  const categories = useMemo(
    () =>
      tools.filter(
        (tool, index) => tools.findIndex((item) => item.category === tool.category) === index
      ),
    [tools]
  )
  if (!tools.length) return null

  const toggle = (id: number): void => {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <section className="chat-tool-section" aria-label={`${tools.length} tool calls`}>
      <button
        aria-expanded={open}
        className="chat-tool-section-head"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <span className="chat-tool-stack" aria-hidden="true">
          {categories.slice(0, 10).map((tool, index) => (
            <span
              className="chat-tool-stack-item"
              key={tool.category}
              style={{
                transform: `rotate(${categories.length > 1 ? (index % 2 ? -8 : 8) : 0}deg)`,
                zIndex: index + 1
              }}
            >
              <ToolIcon category={tool.category} />
            </span>
          ))}
          {categories.length > 10 ? (
            <span className="chat-tool-overflow">+{categories.length - 10}</span>
          ) : null}
        </span>
        <strong>
          Used {tools.length} tool{tools.length === 1 ? '' : 's'}
        </strong>
        <ChevronDown
          aria-hidden="true"
          className={open ? 'is-open' : ''}
          size={15}
          strokeWidth={1.6}
        />
      </button>

      <div className={open ? 'chat-tool-section-content is-open' : 'chat-tool-section-content'}>
        <div>
          {tools.map((tool, index) => {
            const hasArguments = Boolean(tool.arguments && Object.keys(tool.arguments).length)
            const hasOutput = Boolean(tool.message.content.trim())
            const hasDetails = hasArguments || hasOutput
            const callOpen = expanded.has(tool.message.id)
            return (
              <div className="chat-tool-step" key={tool.message.id}>
                <div className="chat-tool-rail" aria-hidden="true">
                  <ToolIcon category={tool.category} />
                  {index < tools.length - 1 ? <i /> : null}
                </div>
                <div className="chat-tool-step-content">
                  <button
                    aria-expanded={hasDetails ? callOpen : undefined}
                    className="chat-tool-step-head"
                    disabled={!hasDetails}
                    onClick={() => hasDetails && toggle(tool.message.id)}
                    type="button"
                  >
                    <strong>{toolLabel(tool.name)}</strong>
                    {hasDetails ? (
                      <ChevronDown
                        aria-hidden="true"
                        className={callOpen ? 'is-open' : ''}
                        size={12}
                        strokeWidth={1.6}
                      />
                    ) : null}
                  </button>
                  <span className="chat-tool-category">{tool.categoryLabel}</span>
                  {callOpen && hasDetails ? (
                    <div className="chat-tool-detail">
                      {hasArguments ? (
                        <div>
                          <span>Input</span>
                          <pre>{JSON.stringify(tool.arguments, null, 2)}</pre>
                        </div>
                      ) : null}
                      {hasOutput ? (
                        <div>
                          <span>Output</span>
                          <div className="chat-tool-body">
                            <Markdown content={tool.message.content} />
                          </div>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
