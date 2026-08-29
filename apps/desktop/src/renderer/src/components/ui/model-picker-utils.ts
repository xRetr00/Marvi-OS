import type { ModelCard, ModelProvider } from '../../../../shared/runtime'

const MODEL_BRAND_ALIASES: Readonly<Record<string, string>> = Object.freeze({
  'aion-labs': 'aionlabs',
  'arcee-ai': 'arcee',
  'bytedance-seed': 'bytedance',
  'ibm-granite': 'ibm',
  'inception-labs': 'inception',
  'meta-llama': 'meta',
  mistralai: 'mistral',
  moonshotai: 'moonshot',
  'x-ai': 'xai',
  'z-ai': 'zhipu'
})

export function modelBrandKey(modelId: string, provider: string): string {
  const owner = (modelId.includes('/') ? modelId.split('/', 1)[0] : provider)
    .replace(/^~/, '')
    .trim()
    .toLowerCase()
  return MODEL_BRAND_ALIASES[owner] ?? owner
}

export function modelBrandMonogram(value: string): string {
  const words = value.split(/[^a-z0-9]+/i).filter(Boolean)
  if (words.length > 1)
    return words
      .slice(0, 2)
      .map((word) => word[0])
      .join('')
      .toUpperCase()
  return (words[0] ?? '?').slice(0, 2).toUpperCase()
}

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
