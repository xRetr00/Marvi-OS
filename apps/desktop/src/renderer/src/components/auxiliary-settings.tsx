import React, { useEffect, useState } from 'react'
import { ShieldAlert } from 'lucide-react'

import type { AuxiliaryPage, AuxiliaryRole } from '../../../shared/runtime'
import { ControlButton, ControlEmpty, ControlRow } from './control-surface'
import { Picker } from './ui/picker'

/**
 * Which model does which job.
 *
 * One model was chosen for the hardest thing Marvi does and then used for
 * everything, including a one-sentence yes/no that runs many times an hour.
 * A role may point somewhere cheaper and faster; `auto` keeps the old
 * behaviour, which is a perfectly good answer and the default.
 */
export function AuxiliarySettings(): React.JSX.Element {
  const [page, setPage] = useState<AuxiliaryPage | null>(null)
  const [reload, setReload] = useState(0)
  // What is typed but not yet saved, per role.
  const [models, setModels] = useState<Record<string, string>>({})

  useEffect(() => {
    let gone = false
    void (async () => {
      const next = await window.marvi?.getAuxiliary()
      if (!gone) setPage(next ?? null)
    })()
    return () => {
      gone = true
    }
  }, [reload])

  if (!page) return <span className="construction">UNAVAILABLE</span>
  if (page.providers.length === 0) {
    return (
      <ControlEmpty
        description="Connect a provider on the Models page and these can point at it."
        icon={ShieldAlert}
        title="No providers configured"
      />
    )
  }

  // A provider without a model names nothing, and the Gateway said so on
  // every start: "auxiliary role voice is set to 'openrouter/', which names no
  // model". The picker offered the provider and the detail said to type the
  // model, with nowhere to type it -- so choosing anything wrote a value that
  // could only be ignored. Both halves are saved together or not at all.
  const choose = async (role: AuxiliaryRole, provider: string, model: string): Promise<void> => {
    const value = provider && model.trim() ? `${provider}${page.separator}${model.trim()}` : ''
    if (value === (role.auto ? '' : `${role.provider}${page.separator}${role.model}`)) return
    await window.marvi?.setProviderSettings({ [role.setting]: value })
    setReload((count) => count + 1)
  }

  // A job pinned to a provider that is no longer the main one is the quiet
  // credit-burn path: you switch your main model away from somewhere, and
  // three background jobs keep spending there because nothing said so. Named
  // rather than cleared, because a deliberate pin is a legitimate thing to
  // have and clearing it automatically would be the surprise.
  const stale = page.roles.filter((role) => !role.auto && role.provider !== page.main)

  const resetAll = async (): Promise<void> => {
    await window.marvi?.setProviderSettings(
      Object.fromEntries(stale.map((role) => [role.setting, '']))
    )
    setReload((count) => count + 1)
  }

  return (
    <>
      {page.roles.map((role) => (
        <ControlRow
          action={
            <div className="provider-actions">
              <Picker
                options={[
                  { value: '', label: 'Auto', detail: 'Use the main model, as before' },
                  ...page.providers.map((provider) => ({
                    value: provider.name,
                    label: provider.label,
                    detail: 'Name the model beside it'
                  }))
                ]}
                value={role.provider}
                onChange={(next) => void choose(role, next, models[role.key] ?? role.model)}
                placeholder="Auto"
              />
              <input
                aria-label={`Model for ${role.title}`}
                className="control-input"
                disabled={!role.provider}
                onChange={(event) =>
                  setModels((current) => ({ ...current, [role.key]: event.target.value }))
                }
                onBlur={() => void choose(role, role.provider, models[role.key] ?? '')}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    void choose(role, role.provider, models[role.key] ?? '')
                  }
                }}
                placeholder="model id"
                value={models[role.key] ?? role.model}
              />
            </div>
          }
          description={role.gain ? `${role.why} ${role.gain}` : role.why}
          key={role.key}
          title={role.title}
        />
      ))}
      {stale.length > 0 ? (
        <ControlRow
          action={<ControlButton onClick={() => void resetAll()}>Reset all to main</ControlButton>}
          description={`${stale.map((role) => role.title).join(', ')} still ${
            stale.length === 1 ? 'runs' : 'run'
          } on ${
            new Set(stale.map((role) => role.provider)).size === 1
              ? stale[0].provider
              : 'other providers'
          }, not your main model. A job pinned to a provider you have stopped using goes on
          spending there quietly.`}
          icon={ShieldAlert}
          title="Pinned away from your main model"
        />
      ) : null}
      {page.roles.some((role) => !role.auto) ? (
        <ControlRow
          description={page.roles
            .filter((role) => !role.auto)
            .map((role) => `${role.title}: ${role.provider}/${role.model || '(no model named)'}`)
            .join(' · ')}
          title="Currently"
        />
      ) : null}
    </>
  )
}
