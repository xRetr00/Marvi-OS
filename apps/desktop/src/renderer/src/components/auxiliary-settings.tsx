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

  const choose = async (role: AuxiliaryRole, value: string): Promise<void> => {
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
            <Picker
              options={[
                {
                  value: '',
                  label: 'Auto',
                  detail: 'Use the main model, as before'
                },
                ...page.providers.map((provider) => ({
                  value: `${provider.name}${page.separator}`,
                  label: provider.label,
                  detail: 'Type the model after choosing'
                }))
              ]}
              value={role.auto ? '' : `${role.provider}${page.separator}`}
              onChange={(next) => void choose(role, next)}
              placeholder="Auto"
            />
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
