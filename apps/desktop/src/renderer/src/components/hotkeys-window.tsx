/**
 * The keyboard shortcuts window: every global hotkey, and changing one.
 *
 * Recording rather than typing. A text field for `Alt+Shift+M` asks a person
 * to know Electron's accelerator spelling and gets `alt shift m` back; here
 * the combination is pressed, and the same pure helper the main process
 * validates with turns the key event into the stored string.
 *
 * Main stays authoritative: every edit goes to it, and what comes back --
 * including "another app is using this combination" -- is what the list shows.
 */
import { useCallback, useEffect, useState } from 'react'
import { Keyboard, RotateCcw, X } from 'lucide-react'

import { haptic } from '../lib/haptics'
import {
  HOTKEY_DEFINITIONS,
  type HotkeyAction,
  type HotkeyReport,
  acceleratorFrom
} from '../../../shared/hotkeys'

export function KeyCombo({ accelerator }: { accelerator: string }): React.JSX.Element {
  if (!accelerator) return <span className="hotkeys-off">Off</span>
  return (
    <span className="hotkeys-combo">
      {accelerator.split('+').map((part) => (
        <kbd key={part}>{part}</kbd>
      ))}
    </span>
  )
}

export function HotkeysWindow({ onClose }: { onClose: () => void }): React.JSX.Element {
  const [report, setReport] = useState<HotkeyReport | null>(null)
  const [recording, setRecording] = useState<HotkeyAction | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    void (async () => {
      const current = (await window.marvi?.getHotkeys()) ?? null
      if (alive) setReport(current)
    })()
    return () => {
      alive = false
    }
  }, [])

  const send = useCallback(async (action: HotkeyAction, accelerator: string): Promise<void> => {
    const next = await window.marvi?.setHotkey(action, accelerator)
    if (!next) return
    setReport(next)
    setError(next.error ?? '')
    haptic(next.error ? 'error' : 'success')
  }, [])

  // While recording, the window swallows the whole keyboard: the combination
  // being recorded may well be one this page would otherwise act on.
  useEffect(() => {
    if (!recording) return
    const down = (event: KeyboardEvent): void => {
      event.preventDefault()
      event.stopPropagation()
      if (event.key === 'Escape') {
        setRecording(null)
        return
      }
      const accelerator = acceleratorFrom(event)
      if (!accelerator) return // still only modifiers held
      setRecording(null)
      void send(recording, accelerator)
    }
    window.addEventListener('keydown', down, true)
    return () => window.removeEventListener('keydown', down, true)
  }, [recording, send])

  useEffect(() => {
    if (recording) return
    const escape = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', escape)
    return () => window.removeEventListener('keydown', escape)
  }, [onClose, recording])

  const reset = async (): Promise<void> => {
    const next = await window.marvi?.resetHotkeys()
    if (next) {
      setReport(next)
      setError('')
    }
  }

  return (
    <div
      className="connector-modal-shell"
      onClick={(event) => {
        if (event.target === event.currentTarget && !recording) onClose()
      }}
      role="presentation"
    >
      <div
        aria-label="Keyboard shortcuts"
        aria-modal="true"
        className="connector-modal hotkeys-modal"
        role="dialog"
      >
        <button aria-label="Close" className="connector-modal-close" onClick={onClose} type="button">
          <X aria-hidden="true" size={14} />
        </button>

        <header className="connector-modal-head">
          <div>
            <h3>
              <Keyboard aria-hidden="true" size={16} /> Keyboard shortcuts
            </h3>
            <p>
              These work anywhere in Windows, whether or not Marvi has focus. Click a combination to
              record a new one, Escape to cancel.
            </p>
          </div>
        </header>

        {error ? <p className="hotkeys-error">{error}</p> : null}

        <ul className="hotkeys-list">
          {HOTKEY_DEFINITIONS.map((definition) => {
            const accelerator = report?.bindings?.[definition.id] ?? ''
            const problem = report?.problems?.[definition.id] ?? ''
            const listening = recording === definition.id
            return (
              <li className="hotkeys-row" key={definition.id}>
                <div className="hotkeys-what">
                  <span className="hotkeys-label">{definition.label}</span>
                  <span className="hotkeys-description">{definition.description}</span>
                  {problem ? <span className="hotkeys-problem">{problem}</span> : null}
                </div>
                <div className="hotkeys-controls">
                  <button
                    aria-label={`Change the shortcut for ${definition.label}`}
                    className={`hotkeys-record${listening ? ' is-listening' : ''}`}
                    onClick={() => {
                      haptic('tap')
                      setError('')
                      setRecording(listening ? null : definition.id)
                    }}
                    type="button"
                  >
                    {listening ? (
                      <span className="hotkeys-listening">Press a combination…</span>
                    ) : (
                      <KeyCombo accelerator={accelerator} />
                    )}
                  </button>
                  <button
                    aria-label={`Turn off the shortcut for ${definition.label}`}
                    className="hotkeys-clear"
                    disabled={!accelerator}
                    onClick={() => void send(definition.id, '')}
                    type="button"
                  >
                    <X aria-hidden="true" size={12} />
                  </button>
                </div>
              </li>
            )
          })}
        </ul>

        <footer className="hotkeys-foot">
          <button className="hotkeys-reset" onClick={() => void reset()} type="button">
            <RotateCcw aria-hidden="true" size={12} /> Restore defaults
          </button>
          <span className="hotkeys-note">Saved as you change them.</span>
        </footer>
      </div>
    </div>
  )
}
