import { useEffect, useState } from 'react'
import { Brain, Layers } from 'lucide-react'
import { ControlPage, ControlRow, ControlSection } from './control-surface'

export const CONTEXT_SOURCES = [
  ['room', 'Room'],
  ['vision', 'Vision'],
  ['weather', 'Weather'],
  ['map', 'Map and location'],
  ['activity', 'Desktop activity'],
  ['accounts', 'Connected accounts'],
  ['memory', 'Memory'],
  ['continuity', 'Conversation continuity'],
  ['system', 'System status'],
  ['skills', 'Skills'],
  ['plugins', 'Plugin context'],
  ['mind', 'Mind and curiosity']
] as const

export function ContextSettings(): React.JSX.Element {
  const [settings, setSettings] = useState<Record<string, string> | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let alive = true
    const load = async (): Promise<void> => {
      try {
        const page = await window.marvi?.getProviders()
        if (!page) throw new Error('Gateway is unavailable. Reopen settings to retry.')
        if (alive) setSettings(page.settings)
      } catch (cause) {
        if (alive) setError(String(cause))
      }
    }
    void load()
    return () => {
      alive = false
    }
  }, [])

  const change = async (key: string, value: boolean): Promise<void> => {
    setBusy(true)
    setError('')
    try {
      const page = await window.marvi?.setProviderSettings({ [key]: String(value) })
      if (!page) throw new Error('Gateway did not acknowledge the change.')
      setSettings(page.settings)
    } catch (cause) {
      setError(String(cause))
    } finally {
      setBusy(false)
    }
  }
  const toggle = (key: string, label: string, disabled = false): React.JSX.Element => {
    const on = settings?.[key] === 'true' && !disabled
    return (
      <button
        type="button"
        role="switch"
        aria-label={label}
        aria-checked={on}
        disabled={!settings || busy || disabled}
        className={on ? 'mode-switch active' : 'mode-switch'}
        onClick={() => void change(key, !on)}
      >
        {on ? 'On' : 'Off'}
      </button>
    )
  }
  return (
    <ControlPage
      title="Context and Mind"
      className="settings-page"
      description="Choose what Marvi uses automatically. Changes are saved on this computer."
    >
      {error && <p role="alert">{error}</p>}
      {busy && (
        <p role="status">
          Applying change. Mind shutdown waits for active background work to finish.
        </p>
      )}
      <ControlSection icon={Brain} title="Mind power">
        <ControlRow
          title="Mind"
          description="Turn off to stop background Mind jobs, reject new events, and stop and unload its announcer. Stored memories and history are kept."
          action={toggle('MARVI_MIND_ENABLED', 'Mind power')}
        />
        <ControlRow
          title="Announcer"
          description="Allow the one-shot voice used for announcements and Read aloud. Mind off overrides this preference."
          action={toggle('MARVI_ANNOUNCE', 'Announcer', settings?.MARVI_MIND_ENABLED !== 'true')}
        />
      </ControlSection>
      <ControlSection icon={Layers} title="Automatic context">
        <p>
          Feed Mind controls incoming observations and background reasoning. Include in prompts
          controls automatic context in chat and voice. Feature pages, sensors, and explicitly
          requested tools remain available.
        </p>
        <p>
          Room summaries combine room, camera, and phone facts. If any of Room, Vision, or Map is
          off, their combined summary is withheld. Weather feeding also needs Map.
        </p>
        <p>
          Changes apply to the next turn. Information already spoken or written in conversation
          history is kept.
        </p>
        {CONTEXT_SOURCES.map(([source, label]) => (
          <ControlRow
            key={source}
            title={label}
            action={
              <div className="context-settings-switches">
                <label>
                  Feed Mind{' '}
                  {toggle(
                    `MARVI_CONTEXT_MIND_${source.toUpperCase()}`,
                    `${label}: Feed Mind`,
                    settings?.MARVI_MIND_ENABLED !== 'true'
                  )}
                </label>
                <label>
                  Include in prompts{' '}
                  {toggle(
                    `MARVI_CONTEXT_PROMPT_${source.toUpperCase()}`,
                    `${label}: Include in prompts`
                  )}
                </label>
              </div>
            }
          />
        ))}
      </ControlSection>
    </ControlPage>
  )
}
