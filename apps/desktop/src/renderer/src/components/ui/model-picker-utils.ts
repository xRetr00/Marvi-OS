import type { ModelCard, ModelProvider } from '../../../../shared/runtime'

export interface ModelPickerGroup {
  models: ModelCard[]
  provider: ModelProvider
}

export function filterModelGroups(providers: ModelProvider[], query: string): ModelPickerGroup[] {
  const needle = query.trim().toLowerCase()
  return providers
    .map((provider) => ({
      provider,
      models: provider.models.filter((model) =>
        `${provider.label} ${provider.provider} ${model.name} ${model.id}`
          .toLowerCase()
          .includes(needle)
      )
    }))
    .filter((group) => group.models.length > 0)
}

export function modelEffortLabel(value: string, fallback: string): string {
  if (!value) return fallback
  if (value === 'xhigh') return 'XHigh'
  return value.charAt(0).toUpperCase() + value.slice(1)
}

export function modelEffortChoices(
  model: ModelCard,
  defaultLabel: string
): Array<{ label: string; value: string }> {
  if (!model.reasons) return []
  return ['', ...model.efforts].map((value) => ({
    label: modelEffortLabel(value, defaultLabel),
    value
  }))
}
