/**
 * The two cards beside the orb: what she is doing, and what is coming up.
 *
 * The Voice page could name the models and nothing else. A turn that paused
 * for four seconds looked the same whether she was searching the web, waiting
 * on the room bridge, or had simply stopped — and the transcript only shows an
 * answer once it exists, never the reaching for it. Chat has had both of these
 * the whole time: a context meter in its status bar and a collapsed "Used N
 * tools" stack under every answer.
 *
 * So these are Chat's components, not new ones. `status-context-*` and
 * `chat-tool-*` are the same class names, styled once in `chat/chat.css`,
 * which is global because Vite hoists it out of `Chat.tsx`. A second visual
 * language for the same two ideas is how a product starts looking like two
 * products.
 */
import { useEffect, useMemo, useState } from 'react'
import {
  addMonths,
  format,
  getDate,
  getDaysInMonth,
  isSameDay,
  isToday,
  startOfMonth,
  subMonths
} from 'date-fns'
import { motion } from 'framer-motion'
import {
  BrainCircuit,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  FileText,
  Globe2,
  Home,
  Mail,
  Search,
  TerminalSquare,
  Wrench,
  type LucideIcon
} from 'lucide-react'

import { compactTokens } from '../chat/context-breakdown'
import { sourcesFrom } from './voice-sources'

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

/** The same mapping Chat uses, so one tool wears one icon on both surfaces. */
function categoryOf(name: string): string {
  const lower = name.toLowerCase()
  if (/mail|gmail/.test(lower)) return 'email'
  if (/calendar|schedule/.test(lower)) return 'calendar'
  if (/search/.test(lower)) return 'search'
  if (/web|fetch|browser/.test(lower)) return 'web'
  if (/memory|recall|remember|forget/.test(lower)) return 'memory'
  if (/room|light|device|presence/.test(lower)) return 'room'
  if (/file|document|attachment/.test(lower)) return 'file'
  if (/terminal|command|process|shell/.test(lower)) return 'terminal'
  return name.split(/[_-]/)[0] || 'general'
}

function toolLabel(value: string): string {
  return value
    .replaceAll(/[_-]+/g, ' ')
    .trim()
    .replace(/^\w/, (letter) => letter.toUpperCase())
}

export interface VoiceCall {
  id: string
  tool: string
  arguments: Record<string, unknown>
  outcome: 'running' | 'ok' | 'failed' | 'abandoned'
  ms: number
  detail?: string
}

export interface VoiceActivity {
  calls: VoiceCall[]
  running: number
  context: { used: number; window: number; turns: number }
}

/** Poll a Gateway endpoint, quietly. A card that cannot load is a card that
 * shows nothing, never an error over the top of the orb. */
function usePolled<T>(read: () => Promise<unknown>, ms: number): T | null {
  const [value, setValue] = useState<T | null>(null)
  useEffect(() => {
    let gone = false
    const ask = async (): Promise<void> => {
      const body = await read()
      // Only on an answer. A failed poll leaves the last good state on screen
      // rather than blanking the card every time the Gateway restarts.
      if (!gone && body) setValue(body as T)
    }
    void ask()
    const timer = setInterval(() => void ask(), ms)
    return () => {
      gone = true
      clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ms])
  return value
}

function ToolIcon({ category }: { category: string }): React.JSX.Element {
  const Icon = CATEGORY_ICONS[category] ?? Wrench
  return (
    <span className="chat-tool-icon" data-category={category}>
      <Icon aria-hidden="true" size={15} strokeWidth={1.6} />
    </span>
  )
}

/**
 * How full the model's context is, and what she has reached for.
 *
 * Collapsed by default and open on the running call, because the two states
 * this card is read in are different questions: "is anything happening" wants
 * one glance, and "what did she just do" wants the list.
 */
export function VoiceActivityCard({ rig }: { rig?: React.ReactNode }): React.JSX.Element | null {
  const activity = usePolled<VoiceActivity>(
    () => window.marvi?.getVoiceActivity() ?? Promise.resolve(null),
    1200
  )
  // The pickers show even before the first poll answers: they are the part of
  // this card that is useful in an idle session.
  const empty: VoiceActivity = { calls: [], running: 0, context: { used: 0, window: 0, turns: 0 } }
  return <ActivityView activity={activity ?? empty} rig={rig} />
}

/**
 * The card itself, given its data.
 *
 * Split from the polling because this project renders tests with
 * `renderToStaticMarkup`, which never runs an effect — a component that
 * fetches its own data is a component with no assertions on it.
 */
export function ActivityView({
  activity,
  rig
}: {
  activity: VoiceActivity
  /** The model and speech pickers, drawn by the page and placed here.
   *
   * They used to float loose above this card, which read as two unrelated
   * panels stacked in a corner. They belong together: the pickers say which
   * models are doing the work and everything below says what the work is. */
  rig?: React.ReactNode
}): React.JSX.Element | null {
  const [open, setOpen] = useState(false)
  const [showSources, setShowSources] = useState(false)

  const { calls, running, context } = activity
  const percent = context.window
    ? Math.min(100, Math.round((context.used / context.window) * 100))
    : null
  // The same twelve cells Chat draws, filled from one number rather than from
  // segments: voice has no cached/pending breakdown to colour by.
  const cells = Array.from({ length: 12 }, (_, index) =>
    percent === null ? 'unknown' : (index + 0.5) / 12 <= percent / 100 ? 'prompt' : 'free'
  )
  const live = calls.filter((call) => call.outcome === 'running')
  const categories = calls.filter(
    (call, index) =>
      calls.findIndex((item) => categoryOf(item.tool) === categoryOf(call.tool)) === index
  )

  const sources = sourcesFrom(calls)

  return (
    <section className="voice-card voice-activity-card" aria-label="What Marvi is doing">
      {rig ? <div className="voice-card-rig">{rig}</div> : null}
      <div className="status-context-breakdown" data-static="true">
        <div className="voice-card-meter">
          <span className="status-context-label">Context</span>
          <span className="status-detail">
            {context.window
              ? `${compactTokens(context.used)}/${compactTokens(context.window)}`
              : '—'}
          </span>
          <span aria-hidden="true" className="status-context-meter">
            {cells.map((cell, index) => (
              <i className={`is-${cell}`} key={index} />
            ))}
          </span>
          <span className="status-context-percent">{percent ?? '—'}%</span>
        </div>
      </div>

      {/* The running call, above the fold and never collapsed. This is the
          half that answers "is it stuck", which is the question the page is
          open for. */}
      {live.length ? (
        <ul className="voice-card-live" aria-live="polite">
          {live.map((call) => (
            <li key={call.id}>
              <ToolIcon category={categoryOf(call.tool)} />
              <strong>{toolLabel(call.tool)}</strong>
              <span className="voice-card-spinner" aria-hidden="true" />
            </li>
          ))}
        </ul>
      ) : null}

      {calls.length ? (
        <>
          <button
            aria-expanded={open}
            className="chat-tool-section-head"
            onClick={() => setOpen((value) => !value)}
            type="button"
          >
            <span className="chat-tool-stack" aria-hidden="true">
              {categories.slice(0, 6).map((call, index) => (
                <span
                  className="chat-tool-stack-item"
                  key={categoryOf(call.tool)}
                  style={{
                    transform: `rotate(${categories.length > 1 ? (index % 2 ? -8 : 8) : 0}deg)`,
                    zIndex: index + 1
                  }}
                >
                  <ToolIcon category={categoryOf(call.tool)} />
                </span>
              ))}
              {categories.length > 6 ? (
                <span className="chat-tool-overflow">+{categories.length - 6}</span>
              ) : null}
            </span>
            <strong>
              Used {calls.length} tool{calls.length === 1 ? '' : 's'}
              {running ? ` · ${running} running` : ''}
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
              {calls.map((call) => (
                <div className="chat-tool-step voice-card-step" key={call.id}>
                  <ToolIcon category={categoryOf(call.tool)} />
                  <span className="voice-card-step-name">{toolLabel(call.tool)}</span>
                  {/* Arguments, because a receipt without them is not one:
                      "forgot something" and "forgot the right thing" look
                      identical without the query beside the name. */}
                  <span className="voice-card-step-args">
                    {Object.entries(call.arguments)
                      .slice(0, 2)
                      .map(([name, value]) => `${name}=${String(value).slice(0, 24)}`)
                      .join(' ')}
                  </span>
                  {call.outcome === 'failed' ? (
                    <CircleAlert aria-label="failed" size={13} strokeWidth={1.8} />
                  ) : call.outcome === 'running' ? (
                    <span className="voice-card-spinner" aria-label="running" />
                  ) : (
                    <CheckCircle2 aria-label="done" size={13} strokeWidth={1.8} />
                  )}
                  {call.ms ? <span className="voice-card-step-ms">{call.ms}ms</span> : null}
                </div>
              ))}
            </div>
          </div>
        </>
      ) : (
        <p className="voice-card-empty">No tools used yet</p>
      )}

      {/* Where she has been, which is a different question from what she did.
          You ask this one when an answer surprises you. */}
      {sources.length ? (
        <>
          <button
            aria-expanded={showSources}
            className="chat-tool-section-head voice-card-sources-head"
            onClick={() => setShowSources((value) => !value)}
            type="button"
          >
            <strong>
              {sources.length} source{sources.length === 1 ? '' : 's'}
            </strong>
            <ChevronDown
              aria-hidden="true"
              className={showSources ? 'is-open' : ''}
              size={14}
              strokeWidth={1.6}
            />
          </button>
          <div
            className={
              showSources ? 'chat-tool-section-content is-open' : 'chat-tool-section-content'
            }
          >
            <ul className="voice-card-sources">
              {sources.map((source) => (
                <li key={`${source.kind}-${source.full}`} title={source.full}>
                  {source.kind === 'web' ? (
                    <Globe2 aria-hidden="true" size={12} strokeWidth={1.6} />
                  ) : (
                    <FileText aria-hidden="true" size={12} strokeWidth={1.6} />
                  )}
                  <span>{source.label}</span>
                  {source.times > 1 ? <em>×{source.times}</em> : null}
                </li>
              ))}
            </ul>
          </div>
        </>
      ) : null}
    </section>
  )
}

export interface CalendarEvent {
  id: string
  title: string
  start: string
  end: string
  location: string
  all_day: boolean
}


/**
 * The month, always drawn, with what is on each day.
 *
 * Adapted from the glass calendar the owner supplied. Two things changed and
 * both are about fitting the app rather than taste: the Tailwind classes
 * became CSS here, because everything else in this renderer is plain CSS and
 * one component in a second styling system is worse than a translation; and
 * the "Weekly / Monthly" tabs are gone, because there is one view and a tab
 * strip with nothing behind it is a promise the card does not keep.
 *
 * `date-fns` and `framer-motion` are the design's own, and are now the app's.
 *
 * The month shows whether anything is scheduled or not. An empty list is a
 * card that looks broken; a month with no dots on it is a month with nothing
 * in it, which is information.
 */
export function CalendarView({
  calendar,
  now,
  onMonth
}: {
  calendar: { connected: boolean; events: CalendarEvent[]; reason?: string }
  now: Date
  /** Told when the month changes, so the page can fetch that month. */
  onMonth?: (month: Date) => void
}): React.JSX.Element {
  const [month, setMonth] = useState(() => startOfMonth(now))
  const [picked, setPicked] = useState(() => now)

  const days = useMemo(() => {
    const first = startOfMonth(month)
    return Array.from({ length: getDaysInMonth(month) }, (_, index) => {
      const date = new Date(first.getFullYear(), first.getMonth(), index + 1)
      return { date, isToday: isToday(date), isSelected: isSameDay(date, picked) }
    })
  }, [month, picked])

  // Which days have something on them, so the strip can carry a dot without
  // the card having to be open to the right day first.
  const busy = useMemo(() => {
    const marked = new Set<string>()
    for (const event of calendar.events) {
      const at = new Date(event.start)
      if (!Number.isNaN(at.getTime())) marked.add(format(at, 'yyyy-MM-dd'))
    }
    return marked
  }, [calendar.events])

  const onPicked = calendar.events.filter((event) => {
    const at = new Date(event.start)
    return !Number.isNaN(at.getTime()) && isSameDay(at, picked)
  })

  const goto = (next: Date): void => {
    setMonth(next)
    onMonth?.(next)
  }

  return (
    <section className="voice-card voice-calendar-card" aria-label="Calendar">
      <header className="voice-calendar-head">
        <motion.p
          key={format(month, 'MMMM yyyy')}
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25 }}
          className="voice-calendar-month"
        >
          {format(month, 'MMMM')}
        </motion.p>
        <div className="voice-calendar-nav">
          <button
            aria-label="Previous month"
            onClick={() => goto(subMonths(month, 1))}
            type="button"
          >
            <ChevronLeft aria-hidden="true" size={15} strokeWidth={1.8} />
          </button>
          <button aria-label="Next month" onClick={() => goto(addMonths(month, 1))} type="button">
            <ChevronRight aria-hidden="true" size={15} strokeWidth={1.8} />
          </button>
        </div>
      </header>

      <div className="voice-calendar-strip">
        {days.map((day) => (
          <div className="voice-calendar-day" key={format(day.date, 'yyyy-MM-dd')}>
            <span className="voice-calendar-dow">{format(day.date, 'E').charAt(0)}</span>
            <button
              aria-current={day.isToday ? 'date' : undefined}
              aria-pressed={day.isSelected}
              className={day.isSelected ? 'is-selected' : undefined}
              onClick={() => setPicked(day.date)}
              type="button"
            >
              {getDate(day.date)}
              {/* Today keeps its own mark even when another day is picked,
                  so scrolling three months out never loses where you are. */}
              {day.isToday && !day.isSelected ? <i className="voice-calendar-today" /> : null}
              {busy.has(format(day.date, 'yyyy-MM-dd')) && !day.isSelected ? (
                <i className="voice-calendar-dot" />
              ) : null}
            </button>
          </div>
        ))}
      </div>

      <div className="voice-calendar-rule" />

      {!calendar.connected ? (
        // Distinct from an empty day: only one of these is something the user
        // can act on.
        <p className="voice-card-empty">Calendar not connected</p>
      ) : onPicked.length === 0 ? (
        <p className="voice-card-empty">Nothing on {format(picked, 'EEE d MMM')}</p>
      ) : (
        <ul className="voice-calendar-events">
          {onPicked.slice(0, 4).map((event) => (
            <li key={event.id || event.start}>
              <span className="voice-calendar-when">{when(event, now)}</span>
              <span className="voice-calendar-title">{event.title}</span>
              {event.location ? <span className="voice-calendar-where">{event.location}</span> : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** "in 20 min", "14:30", "All day" — whichever is shortest and still says
 * enough. The renderer owns this because it knows the user's clock. */
function when(event: CalendarEvent, now: Date): string {
  const start = new Date(event.start)
  if (Number.isNaN(start.getTime())) return ''
  if (event.all_day) return 'All day'
  const minutes = Math.round((start.getTime() - now.getTime()) / 60000)
  if (minutes >= 0 && minutes < 60) return `in ${minutes} min`
  return format(start, 'HH:mm')
}

/**
 * What is on the calendar, from the connected account.
 *
 * Read from `/calendar/upcoming` rather than through the tool path: a page is
 * not a model, and it wants the same events every minute without a
 * confirmation flow, an audit line, or an external-data envelope around them.
 *
 * Marvi reaches the same calendar through `calendar_events`, `calendar_add`,
 * `calendar_move` and `calendar_remove`, so what is drawn here is what she can
 * change — the card and the assistant look at one thing rather than two views
 * that can disagree.
 */
export function CalendarCard(): React.JSX.Element {
  const calendar = usePolled<{ connected: boolean; events: CalendarEvent[]; reason?: string }>(
    () => window.marvi?.getCalendar() ?? Promise.resolve(null),
    60_000
  )
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 30_000)
    return () => clearInterval(timer)
  }, [])
  // Drawn before the first answer arrives, and drawn when there is nothing on
  // it. The month is the card; the events are what is written on it.
  return <CalendarView calendar={calendar ?? { connected: false, events: [] }} now={now} />
}
