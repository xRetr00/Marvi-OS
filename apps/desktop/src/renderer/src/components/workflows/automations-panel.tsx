import { t } from '../../store/locale'
import { Tr } from '../../store/locale'
/**
 * Rules: when X happens, do Y. Written here, never switched on by Marvi.
 *
 * The form is five fields because a rule is five things -- a name, a trigger,
 * an optional condition, an action and its arguments -- and anything that
 * looked like a canvas of draggable nodes would be a worse way to write those.
 *
 * Two facts the panel has to keep saying, because both are easy to assume
 * wrong. A rule Marvi proposes arrives switched off and says so. And an action
 * goes through the ordinary tool path, so a sensitive one still waits for a
 * tap in Confirm mode -- an automation asks for a tool call, it does not get a
 * private way to make one.
 */
import { useCallback, useEffect, useState } from 'react'
import { Play, Plus, Sparkles, Trash2, Webhook, X } from 'lucide-react'

import type { AutomationPage, AutomationRule } from '../../../../shared/runtime'

/** What each trigger is, in the words of somebody choosing between them. */
const TRIGGERS: Record<string, string> = {
  schedule: 'a time comes round',
  room: 'something happens in the room — presence, a sensor, a light',
  account: 'an item arrives in a connected account',
  app_focus: 'an app takes the foreground',
  webhook: 'a local program calls a URL'
}

export function AutomationsPanel(): React.JSX.Element {
  const [page, setPage] = useState<AutomationPage | null>(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState('')
  const [ran, setRan] = useState<{ id: string; detail: string } | null>(null)

  const load = useCallback(async () => {
    setPage((await window.marvi?.getAutomations()) ?? null)
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const toggle = async (rule: AutomationRule): Promise<void> => {
    setBusy(rule.id)
    await window.marvi?.setAutomationEnabled(rule.id, !rule.enabled)
    setBusy('')
    void load()
  }

  const dryRun = async (rule: AutomationRule): Promise<void> => {
    setBusy(rule.id)
    const done = (await window.marvi?.runAutomation(rule.id, {})) as {
      ran?: { ok?: boolean; detail?: string }[]
    } | null
    setBusy('')
    const first = done?.ran?.[0]
    setRan({
      id: rule.id,
      detail: first
        ? `${first.ok ? 'ran' : 'did not run'}: ${first.detail || 'no detail'}`
        : 'nothing matched — the rule is off, or its condition did not hold for an empty event'
    })
    void load()
  }

  const remove = async (rule: AutomationRule): Promise<void> => {
    setBusy(rule.id)
    await window.marvi?.removeAutomation(rule.id)
    setBusy('')
    void load()
  }

  const rules = page?.automations ?? []
  const proposed = rules.filter((rule) => rule.proposed_by !== 'owner' && !rule.enabled)

  return (
    <section className="wf-rules">
      <header className="wf-head">
        <div>
          <h3>
            <Tr text={'Rules'} />
          </h3>
          <p>
            <Tr
              text={
                'When something happens, do one thing — matched exactly, with no model deciding whether today is different. Actions still go through confirmation.'
              }
            />
          </p>
        </div>
        <button className="cron-new" onClick={() => setOpen(!open)} type="button">
          {open ? <X aria-hidden="true" /> : <Plus aria-hidden="true" />}
          {open ? 'Cancel' : 'New rule'}
        </button>
      </header>

      {proposed.length > 0 ? (
        <p className="wf-proposed">
          <Sparkles aria-hidden="true" size={12} />
          <Tr text={'Marvi suggested'} after />
          {proposed.length === 1 ? 'a rule' : `${proposed.length} rules`}
          <Tr text={'. They arrive switched off — nothing happens until you turn one on.'} after />
        </p>
      ) : null}

      {open ? (
        <RuleForm
          onDone={() => {
            setOpen(false)
            void load()
          }}
          triggers={page?.triggers ?? []}
        />
      ) : null}

      <ul className="wf-rule-list">
        {rules.map((rule) => (
          <li className={rule.enabled ? 'is-on' : ''} key={rule.id}>
            <div className="wf-rule-main">
              <button
                aria-label={rule.enabled ? `Turn off ${rule.name}` : `Turn on ${rule.name}`}
                aria-pressed={rule.enabled}
                className="wf-switch"
                disabled={busy === rule.id}
                onClick={() => void toggle(rule)}
                type="button"
              >
                <span />
              </button>
              <div className="wf-rule-words">
                <strong>{rule.name}</strong>
                <span className="wf-rule-when">
                  <Tr text={'when'} after />
                  {TRIGGERS[rule.trigger] ?? rule.trigger}
                  {Object.keys(rule.match).length
                    ? ` · if ${Object.entries(rule.match)
                        .map(([field, value]) => `${field} is ${JSON.stringify(value)}`)
                        .join(' and ')}`
                    : ''}
                  {' · then '}
                  <code>{rule.action}</code>
                </span>
                <span className="wf-rule-last">
                  {rule.last_run
                    ? `last ran ${rule.last_run.slice(0, 16).replace('T', ' ')} — ${rule.last_result}`
                    : 'never run'}
                </span>
                {rule.secret ? <WebhookHint rule={rule} /> : null}
                {ran?.id === rule.id ? <span className="wf-rule-ran">{ran.detail}</span> : null}
              </div>
            </div>
            <div className="wf-rule-acts">
              <button
                aria-label={`Dry run ${rule.name}`}
                disabled={busy === rule.id}
                onClick={() => void dryRun(rule)}
                title={t('Fire it once, by hand, with an empty event')}
                type="button"
              >
                <Play aria-hidden="true" size={12} />
              </button>
              <button
                aria-label={`Delete ${rule.name}`}
                disabled={busy === rule.id}
                onClick={() => void remove(rule)}
                type="button"
              >
                <Trash2 aria-hidden="true" size={12} />
              </button>
            </div>
          </li>
        ))}
        {rules.length === 0 && !open ? (
          <li className="wf-empty-row">
            <Tr
              text={
                'No rules yet. A rule is the one thing here Marvi cannot switch on for herself.'
              }
            />
          </li>
        ) : null}
      </ul>
    </section>
  )
}

/** The URL and the secret a local script needs, and nothing it does not. */
function WebhookHint({ rule }: { rule: AutomationRule }): React.JSX.Element {
  const [shown, setShown] = useState(false)
  return (
    <span className="wf-hook">
      <Webhook aria-hidden="true" size={11} />
      <code>POST /hooks/{rule.id}</code>
      <button onClick={() => setShown(!shown)} type="button">
        {shown ? 'hide secret' : 'show secret'}
      </button>
      {shown ? <code className="wf-secret">x-marvi-secret: {rule.secret}</code> : null}
    </span>
  )
}

/** Five fields, because a rule is five things. */
function RuleForm({
  onDone,
  triggers
}: {
  onDone: () => void
  triggers: string[]
}): React.JSX.Element {
  const [name, setName] = useState('')
  const [trigger, setTrigger] = useState(triggers[0] ?? 'webhook')
  const [action, setAction] = useState('')
  const [args, setArgs] = useState('{}')
  const [match, setMatch] = useState('{}')
  const [error, setError] = useState('')

  const save = async (): Promise<void> => {
    let parsedArgs: Record<string, unknown>
    let parsedMatch: Record<string, unknown>
    try {
      parsedArgs = JSON.parse(args || '{}')
      parsedMatch = JSON.parse(match || '{}')
    } catch {
      setError('The arguments and the condition each have to be a JSON object.')
      return
    }
    if (!name.trim() || !action.trim()) {
      setError('A rule needs a name and something to do.')
      return
    }
    const made = await window.marvi?.addAutomation({
      name: name.trim(),
      trigger,
      action: action.trim(),
      arguments: parsedArgs,
      match: parsedMatch,
      enabled: true
    })
    if (!made) {
      setError('The Gateway would not take that rule. Check the tool name.')
      return
    }
    onDone()
  }

  return (
    <div className="wf-form">
      <label>
        <span>
          <Tr text={'Name'} />
        </span>
        <input
          onChange={(event) => setName(event.target.value)}
          placeholder={t('Warm light when I sit down after six')}
          value={name}
        />
      </label>
      <label>
        <span>
          <Tr text={'When'} />
        </span>
        <select onChange={(event) => setTrigger(event.target.value)} value={trigger}>
          {(triggers.length ? triggers : Object.keys(TRIGGERS)).map((one) => (
            <option key={one} value={one}>
              {one} — {TRIGGERS[one] ?? one}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>
          <Tr text={'If'} />
        </span>
        <input
          onChange={(event) => setMatch(event.target.value)}
          placeholder={'{"kind": "presence"}'}
          value={match}
        />
        <small>
          <Tr text="Plain matching against the event's own fields. Empty means every time." />
        </small>
      </label>
      <label>
        <span>
          <Tr text={'Then'} />
        </span>
        <input
          onChange={(event) => setAction(event.target.value)}
          placeholder={t('room_set_light')}
          value={action}
        />
        <small>
          <Tr text={'A Gateway tool by name. A sensitive one still asks you first.'} />
        </small>
      </label>
      <label>
        <span>
          <Tr text={'With'} />
        </span>
        <input
          onChange={(event) => setArgs(event.target.value)}
          placeholder={'{"state": "warm"}'}
          value={args}
        />
        <small>
          <code>{'{field}'}</code>{' '}
          <Tr
            text={'is filled from the event — into a slot you wrote, never as a new one.'}
            before
            after
          />
        </small>
      </label>
      {error ? <p className="cron-error">{error}</p> : null}
      <button className="wf-save" onClick={() => void save()} type="button">
        <Tr text={'Save rule'} />
      </button>
    </div>
  )
}
