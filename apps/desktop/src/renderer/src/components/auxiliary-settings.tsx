import React, { useCallback, useEffect, useState } from 'react'
import { ShieldAlert } from 'lucide-react'

import type { AuxiliaryPage, AuxiliaryRole, ModelCard } from '../../../shared/runtime'
import { ControlButton, ControlEmpty, ControlRow } from './control-surface'
import { Picker } from './ui/picker'

/**
 * Which model does which job.
 *
 * One model was chosen for the hardest thing Marvi does and then used for
 * everything, including a one-sentence yes/no that runs many times an hour.
 * A role may point somewhere cheaper and faster; `auto` keeps the old
 * behaviour, which is a perfectly good answer and the default.
 *
 * ## Why a draft, and not a picker that saves
 *
 * A role is `provider/model` and is meaningless with half of it -- the Gateway
 * said so on every start: "set to 'openrouter/', which names no model". So the
 * previous version refused to save half, which is right, and saved on every
 * change, which is not: choosing a provider wrote the empty string, the row
 * snapped back to Auto, and the model field stayed disabled because it was
 * disabled until a provider was chosen. There was no order of clicks that
 * worked.
 *
 * The shape here is hermes's, and it is the shape that fits: a row shows what
 * is set, **Change** opens a draft, and nothing reaches the Gateway until
 * Apply. Provider, model and effort are decided together because they are one
 * decision.
 */
export function AuxiliarySettings(): React.JSX.Element {
  const [page, setPage] = useState<AuxiliaryPage | null>(null)
  const [reload, setReload] = useState(0)
  /** The role being edited, or empty. One at a time, as hermes does it. */
  const [editing, setEditing] = useState('')
  const [draft, setDraft] = useState({ provider: '', model: '', effort: '' })
  /** Models per provider, fetched once each and kept while the page is open. */
  const [catalog, setCatalog] = useState<Record<string, ModelCard[]>>({})
  const [fetching, setFetching] = useState('')
  const [busy, setBusy] = useState(false)

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

  // Fetched when a provider is chosen rather than for every provider up front:
  // listing models reaches the provider's API, and doing six of those to open a
  // settings page is six requests for a page most visits only read.
  const load = useCallback(
    async (provider: string): Promise<void> => {
      if (!provider || catalog[provider]) return
      setFetching(provider)
      try {
        const found = await window.marvi?.getModels({ provider })
        const models = found?.providers?.[0]?.models ?? []
        setCatalog((current) => ({ ...current, [provider]: models }))
      } finally {
        setFetching('')
      }
    },
    [catalog]
  )

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

  const begin = (role: AuxiliaryRole): void => {
    setEditing(role.key)
    setDraft({ provider: role.provider, model: role.model, effort: role.effort })
    if (role.provider) void load(role.provider)
  }

  const cancel = (): void => {
    setEditing('')
    setDraft({ provider: '', model: '', effort: '' })
  }

  const apply = async (role: AuxiliaryRole): Promise<void> => {
    if (!draft.provider || !draft.model) return
    setBusy(true)
    try {
      await window.marvi?.setProviderSettings({
        [role.setting]: `${draft.provider}${page.separator}${draft.model}`,
        [role.effortSetting]: draft.effort
      })
      cancel()
      setReload((count) => count + 1)
    } finally {
      setBusy(false)
    }
  }

  const toAuto = async (role: AuxiliaryRole): Promise<void> => {
    setBusy(true)
    try {
      // The effort goes with it. An effort left behind would apply to the main
      // model the moment this role stopped naming one of its own.
      await window.marvi?.setProviderSettings({ [role.setting]: '', [role.effortSetting]: '' })
      setReload((count) => count + 1)
    } finally {
      setBusy(false)
    }
  }

  // A job pinned to a provider that is no longer the main one is the quiet
  // credit-burn path: you switch your main model away from somewhere, and
  // three background jobs keep spending there because nothing said so. Named
  // rather than cleared, because a deliberate pin is a legitimate thing to
  // have and clearing it automatically would be the surprise.
  const stale = page.roles.filter((role) => !role.auto && role.provider !== page.main)

  const resetAll = async (): Promise<void> => {
    await window.marvi?.setProviderSettings(
      Object.fromEntries(stale.flatMap((role) => [[role.setting, ''], [role.effortSetting, '']]))
    )
    setReload((count) => count + 1)
  }

  const models = catalog[draft.provider] ?? []
  const chosen = models.find((model) => model.id === draft.model)

  return (
    <>
      {page.roles.map((role) => (
        <ControlRow
          action={
            editing === role.key ? null : (
              <div className="provider-actions">
                {role.auto ? null : (
                  <ControlButton disabled={busy} onClick={() => void toAuto(role)}>
                    Use main
                  </ControlButton>
                )}
                <ControlButton disabled={busy} onClick={() => begin(role)}>
                  Change
                </ControlButton>
              </div>
            )
          }
          description={
            editing === role.key ? (
              <span className="aux-draft">
                <Picker
                  options={page.providers.map((provider) => ({
                    value: provider.name,
                    label: provider.label,
                    detail: provider.name === page.main ? 'Your main provider' : ''
                  }))}
                  value={draft.provider}
                  onChange={(next) => {
                    // The model belonged to the old provider. Keeping it would
                    // save a pairing that names nothing.
                    setDraft({ provider: next, model: '', effort: '' })
                    void load(next)
                  }}
                  placeholder="Provider"
                />
                <Picker
                  options={models.map((model) => ({
                    value: model.id,
                    label: model.name || model.id,
                    detail: model.reasons ? 'Reasons' : ''
                  }))}
                  value={draft.model}
                  onChange={(next) =>
                    setDraft((current) => ({ ...current, model: next, effort: '' }))
                  }
                  placeholder={
                    !draft.provider
                      ? 'Choose a provider first'
                      : fetching === draft.provider
                        ? 'Fetching models'
                        : models.length === 0
                          ? 'This provider listed nothing'
                          : 'Model'
                  }
                />
                {/* Only where it means something. `efforts` is per model rather
                    than per provider because a gateway fronts both kinds under
                    one credential, and an effort sent to a model that cannot
                    reason is a setting that silently does nothing. */}
                {chosen && chosen.efforts.length > 0 ? (
                  <Picker
                    options={[
                      { value: '', label: 'Default', detail: "The model's own setting" },
                      ...chosen.efforts.map((effort) => ({
                        value: effort,
                        label: effort,
                        detail: ''
                      }))
                    ]}
                    value={draft.effort}
                    onChange={(next) => setDraft((current) => ({ ...current, effort: next }))}
                    placeholder="Default"
                  />
                ) : null}
                <span className="provider-actions">
                  <ControlButton
                    disabled={!draft.provider || !draft.model || busy}
                    onClick={() => void apply(role)}
                  >
                    {busy ? 'Saving' : 'Apply'}
                  </ControlButton>
                  <ControlButton onClick={cancel}>Cancel</ControlButton>
                </span>
              </span>
            ) : (
              <>
                {role.gain ? `${role.why} ${role.gain}` : role.why}
                <br />
                <small className="aux-current">
                  {role.auto
                    ? 'Auto — uses your main model'
                    : `${role.provider} · ${role.model}${
                        role.effort ? ` · ${role.effort} effort` : ''
                      }`}
                </small>
              </>
            )
          }
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
    </>
  )
}
