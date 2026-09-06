/**
 * Cronjobs: the things Marvi does on a timer without being asked.
 *
 * Two failures in the page this replaces, and they compound.
 *
 * The first is that it never said what the two kinds of job *are*. `mode` was
 * a pair of radio buttons labelled "action" and "agent", which is the name of
 * a field in a database, and choosing wrong is not obvious until the job runs
 * and does nothing like what you meant. An action is a fixed thing the Gateway
 * already knows how to do; an agent job is a brief that Marvi reads and works
 * through with tools. Those are very different amounts of trust and cost, and
 * the form asked you to pick between them in one word each.
 *
 * The second is that the model was Marvi's automatic choice and there was no
 * way to say otherwise per job. A nightly summary and a five-minute inbox
 * check should not be the same model: one wants a good one once a day, the
 * other wants a cheap one three hundred times. Providers and models are
 * fetched the same way `auxiliary-settings` fetches them -- on demand, when a
 * provider is chosen, because listing models reaches the provider's API.
 */
import { Bot, ChevronDown, Cpu, Plus, Terminal, X } from 'lucide-react'
import React, { useCallback, useEffect, useState } from 'react'

import type { ModelCard, NewSchedule, SchedulePage } from '../../../shared/runtime'
import { ScheduleCards } from './schedule-cards'
import { WhenPicker } from './when-picker'

/** What each kind of job is, in the words somebody choosing would need. */
const KINDS = [
  {
    id: 'action' as const,
    icon: Terminal,
    title: 'A fixed action',
    what: 'Something the Gateway already knows how to do: say a reminder out loud, run one named action.',
    costs: 'No model, no tokens. Predictable to the letter.',
    example: 'At 07:00 every weekday, say "stand-up in ten minutes".'
  },
  {
    id: 'agent' as const,
    icon: Bot,
    title: 'A task she works through',
    what: 'A brief in your own words. Marvi reads it, decides what to do, and uses tools to do it.',
    costs: 'Costs a model call every run, and can do anything its tools allow.',
    example: 'Every morning, check my inbox and calendar and tell me what actually needs me today.'
  }
]

export function CronjobsPage(): React.JSX.Element {
  const [page, setPage] = useState<SchedulePage | null>(null)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const [name, setName] = useState('')
  const [when, setWhen] = useState('')
  const [mode, setMode] = useState<'action' | 'agent'>('action')
  const [message, setMessage] = useState('')
  const [action, setAction] = useState('')
  const [prompt, setPrompt] = useState('')
  const [insist, setInsist] = useState(false)
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [effort, setEffort] = useState('')
  const [delivery, setDelivery] = useState('local')
  const [toolNames, setToolNames] = useState<string[]>([])

  const [providers, setProviders] = useState<{ name: string; label: string }[]>([])
  const [catalog, setCatalog] = useState<Record<string, ModelCard[]>>({})
  const [fetching, setFetching] = useState('')

  const refresh = useCallback(async (): Promise<void> => {
    const next = await window.marvi?.getSchedules()
    if (next) setPage(next)
  }, [])

  useEffect(() => {
    // Both awaited inside one async body rather than called straight from the
    // effect: a `setState` reached synchronously from an effect cascades a
    // render, and `refresh()` can resolve that fast from a warm Gateway.
    let gone = false
    void (async () => {
      const [jobs, aux] = await Promise.all([
        window.marvi?.getSchedules(),
        // The provider list comes from where the auxiliary roles get theirs,
        // so a job can be pinned to anything Marvi could already talk to.
        window.marvi?.getAuxiliary()
      ])
      if (gone) return
      if (jobs) setPage(jobs)
      if (aux) setProviders(aux.providers)
    })()
    return () => {
      gone = true
    }
  }, [])

  /** Models for one provider, fetched once. Listing them reaches its API. */
  const loadModels = useCallback(
    async (which: string): Promise<void> => {
      if (!which || catalog[which]) return
      setFetching(which)
      try {
        const found = await window.marvi?.getModels({ provider: which })
        setCatalog((current) => ({ ...current, [which]: found?.providers?.[0]?.models ?? [] }))
      } finally {
        setFetching('')
      }
    },
    [catalog]
  )

  const act = async (
    id: number,
    choice: 'remove' | 'enable' | 'disable' | 'run'
  ): Promise<void> => {
    const next = await window.marvi?.scheduleAction(id, choice)
    if (next) setPage(next)
    else void refresh()
  }

  const create = async (): Promise<void> => {
    setError('')
    setBusy(true)
    const body: NewSchedule = {
      name,
      when,
      mode,
      insist,
      ...(mode === 'action' ? { message, action: action || undefined } : { prompt }),
      ...(mode === 'agent' ? { provider, model, effort, tool_names: toolNames, delivery } : {})
    }
    const next = await window.marvi?.addSchedule(body)
    setBusy(false)
    if (!next) {
      setError('Marvi would not accept that. Check the time — "every day at 08:00" works.')
      return
    }
    setPage(next)
    setOpen(false)
    setName('')
    setWhen('')
    setMessage('')
    setPrompt('')
    setInsist(false)
  }

  const ready = Boolean(name && when && (mode === 'action' ? true : prompt.trim()))
  const jobs = page?.schedules ?? []

  return (
    <div className="cron-page">
      <header className="cron-head">
        <div>
          <h2>Cronjobs</h2>
          <p>
            Things Marvi does on a timer without being asked — a reminder at a fixed time, or a
            whole task she reads and works through on her own.
          </p>
        </div>
        <button className="cron-new" onClick={() => setOpen(!open)} type="button">
          {open ? <X aria-hidden="true" /> : <Plus aria-hidden="true" />}
          {open ? 'Cancel' : 'New job'}
        </button>
      </header>

      {!page?.running && page && (
        <p className="cron-warn">The scheduler is not running, so nothing here will fire.</p>
      )}

      {open && (
        <section className="cron-form">
          {/* The explanation the old form never gave. Choosing wrong is not
              obvious until the job runs and does nothing like what you meant. */}
          <div className="cron-kinds">
            {KINDS.map((kind) => {
              const Icon = kind.icon
              return (
                <button
                  aria-pressed={mode === kind.id}
                  className={mode === kind.id ? 'cron-kind is-on' : 'cron-kind'}
                  key={kind.id}
                  onClick={() => setMode(kind.id)}
                  type="button"
                >
                  <span className="cron-kind-head">
                    <Icon aria-hidden="true" />
                    <strong>{kind.title}</strong>
                  </span>
                  <span className="cron-kind-what">{kind.what}</span>
                  <span className="cron-kind-costs">{kind.costs}</span>
                  <span className="cron-kind-eg">e.g. {kind.example}</span>
                </button>
              )
            })}
          </div>

          <label className="cron-field">
            <span>Name</span>
            <input
              onChange={(event) => setName(event.target.value)}
              placeholder="Morning briefing"
              type="text"
              value={name}
            />
          </label>

          <div className="cron-field">
            <span>When</span>
            {/* A picker rather than a text box with a grammar behind it. See
                `when-picker`: the obvious thing to type was rejected, and so
                was every example this form used to offer. */}
            <WhenPicker onChange={setWhen} value={when} />
          </div>

          {mode === 'action' ? (
            <>
              {page && Object.keys(page.actions).length > 0 && (
                <label className="cron-field">
                  <span>Does</span>
                  <select onChange={(event) => setAction(event.target.value)} value={action}>
                    <option value="">Say something out loud</option>
                    {Object.entries(page.actions).map(([id, describes]) => (
                      <option key={id} value={id}>
                        {describes}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              <label className="cron-field">
                <span>Says</span>
                <input
                  onChange={(event) => setMessage(event.target.value)}
                  placeholder="Stand-up in ten minutes"
                  type="text"
                  value={message}
                />
              </label>
            </>
          ) : (
            <>
              <label className="cron-field is-tall">
                <span>The brief</span>
                <textarea
                  onChange={(event) => setPrompt(event.target.value)}
                  placeholder="Check my inbox and calendar and tell me what actually needs me today. Keep it under thirty seconds."
                  rows={4}
                  value={prompt}
                />
              </label>

              {/* Per job, because a nightly summary and a five-minute inbox
                  check should not be the same model: one wants a good one once
                  a day, the other a cheap one three hundred times. */}
              <fieldset className="cron-model">
                <legend>
                  <Cpu aria-hidden="true" /> Which model runs it
                </legend>
                <p>Leave these on Automatic and Marvi picks, the same as everything else.</p>
                <div className="cron-model-row">
                  <label>
                    <span>Provider</span>
                    <select
                      onChange={(event) => {
                        setProvider(event.target.value)
                        setModel('')
                        void loadModels(event.target.value)
                      }}
                      value={provider}
                    >
                      <option value="">Automatic</option>
                      {providers.map((one) => (
                        <option key={one.name} value={one.name}>
                          {one.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Model</span>
                    <select
                      disabled={!provider || fetching === provider}
                      onChange={(event) => setModel(event.target.value)}
                      value={model}
                    >
                      <option value="">
                        {fetching === provider ? 'Loading…' : 'Provider default'}
                      </option>
                      {(catalog[provider] ?? []).map((card) => (
                        <option key={card.id} value={card.id}>
                          {card.id}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Effort</span>
                    <select onChange={(event) => setEffort(event.target.value)} value={effort}>
                      <option value="">Automatic</option>
                      {(page?.efforts ?? []).map((one) => (
                        <option key={one} value={one}>
                          {one}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              </fieldset>

              <details className="cron-more">
                <summary>
                  <ChevronDown aria-hidden="true" /> Tools and where the answer goes
                </summary>
                <label className="cron-field">
                  <span>Delivery</span>
                  <select onChange={(event) => setDelivery(event.target.value)} value={delivery}>
                    {(
                      page?.delivery_targets ?? [
                        { id: 'local', name: 'Keep it local', available: true }
                      ]
                    ).map((target) => (
                      <option disabled={!target.available} key={target.id} value={target.id}>
                        {target.name}
                        {target.available ? '' : ' — not connected'}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="cron-tools-note">
                  {toolNames.length
                    ? `${toolNames.length} tools selected`
                    : 'All of her tools. Narrow this if the job only needs a few.'}
                </p>
                <div className="cron-tools">
                  {(page?.tools ?? []).map((tool) => (
                    <button
                      className={toolNames.includes(tool) ? 'is-on' : ''}
                      key={tool}
                      onClick={() =>
                        setToolNames((current) =>
                          current.includes(tool)
                            ? current.filter((one) => one !== tool)
                            : [...current, tool]
                        )
                      }
                      type="button"
                    >
                      {tool.replaceAll('_', ' ')}
                    </button>
                  ))}
                </div>
              </details>
            </>
          )}

          <label className="cron-insist">
            <input
              checked={insist}
              onChange={(event) => setInsist(event.target.checked)}
              type="checkbox"
            />
            <span>
              Speak anyway
              <small>
                Ignores quiet hours and sleep mode. For an alarm you mean — an hourly check firing
                out loud at 3am is what quiet hours exists to prevent.
              </small>
            </span>
          </label>

          {error && <p className="cron-error">{error}</p>}

          <button
            className="cron-create"
            disabled={!ready || busy}
            onClick={() => void create()}
            type="button"
          >
            {busy ? 'Creating…' : 'Create job'}
          </button>
        </section>
      )}

      {jobs.length === 0 && page ? (
        <p className="cron-empty">
          Nothing scheduled. A job can be a reminder at a fixed time, or a task Marvi works through
          on her own.
        </p>
      ) : (
        <ScheduleCards onAct={(id, choice) => void act(id, choice)} rows={jobs} />
      )}
    </div>
  )
}
