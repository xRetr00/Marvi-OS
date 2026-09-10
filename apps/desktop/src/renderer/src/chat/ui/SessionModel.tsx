import { useEffect, useState } from 'react'

import type { ModelPage, ProviderPage } from '../../../../shared/runtime'
import { ModelPicker } from '../../components/ui/model-picker'

/**
 * The model for this conversation, and only this one.
 *
 * It overrides the configured default for the turns you send from here and is
 * stored nowhere — close the window and it is gone. That is deliberate: trying
 * a model on one conversation should not silently become the model voice, mind
 * and vision use too.
 */
export function SessionModel({
  value,
  onChange
}: {
  value: { provider?: string; model?: string; effort?: string }
  onChange: (next: { provider?: string; model?: string; effort?: string }) => void
}): React.JSX.Element | null {
  const [page, setPage] = useState<ModelPage | null>(null)
  const [settings, setSettings] = useState<ProviderPage | null>(null)

  useEffect(() => {
    let gone = false
    void (async () => {
      const [next, providers] = await Promise.all([
        window.marvi?.getModels({}),
        window.marvi?.getProviders()
      ])
      if (!gone) {
        setPage(next ?? null)
        setSettings(providers ?? null)
      }
    })()
    return () => {
      gone = true
    }
  }, [])

  const providers = page?.providers ?? []
  if (providers.length === 0) return null
  const defaultProvider = providers.find((provider) => provider.provider === settings?.selected)
  const defaultModel = defaultProvider?.models.find(
    (model) => model.id === defaultProvider.selected
  )
  const defaultSelection =
    defaultProvider?.provider && defaultProvider.selected
      ? { provider: defaultProvider.provider, model: defaultProvider.selected }
      : undefined
  const defaultDetail = defaultProvider
    ? `${defaultModel?.name ?? defaultProvider.selected} · ${defaultProvider.label}`
    : 'Uses the Models setting'

  return (
    <div className="chat-session-model">
      <ModelPicker
        className="chat-model-picker"
        defaultOption={{
          label: 'Default model',
          detail: defaultDetail,
          selection: defaultSelection
        }}
        effort={value.effort ?? ''}
        effortDefaultLabel="Default effort"
        providers={providers}
        side="top"
        value={
          value.model && value.provider ? { provider: value.provider, model: value.model } : null
        }
        onChange={(next, options) => {
          if (!next) return onChange({})
          if (options) return onChange({ ...next, effort: options.effort })
          // Effort is dropped with the model: a level chosen for one model
          // means nothing on another, and may not even be accepted.
          onChange(next)
        }}
        placeholder="Default model"
        searchPlaceholder="Search models…"
      />
    </div>
  )
}
