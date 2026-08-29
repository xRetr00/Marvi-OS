import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { ModelCard, ModelProvider } from '../../../../shared/runtime'
import { filterModelGroups, modelEffortChoices, ModelPicker } from './model-picker'

function model(id: string, name = id): ModelCard {
  return {
    id,
    name,
    provider: 'test',
    context: 128_000,
    efforts: ['low', 'high'],
    reasons: true,
    promptPerMillion: 1,
    completionPerMillion: 2,
    vision: false
  }
}

const providers: ModelProvider[] = [
  {
    provider: 'alpha',
    label: 'Alpha Cloud',
    selected: 'alpha/fast',
    routesUpstream: false,
    reachable: true,
    models: [model('alpha/fast', 'Fast'), model('alpha/deep', 'Deep')]
  },
  {
    provider: 'local',
    label: 'Local Runtime',
    selected: 'local/small',
    routesUpstream: false,
    reachable: true,
    models: [model('local/small', 'Small')]
  }
]

describe('ModelPicker', () => {
  it('preserves provider and model order while searching names, ids, and providers', () => {
    expect(filterModelGroups(providers, '').map((group) => group.provider.provider)).toEqual([
      'alpha',
      'local'
    ])
    expect(filterModelGroups(providers, 'deep')[0].models.map((entry) => entry.id)).toEqual([
      'alpha/deep'
    ])
    expect(filterModelGroups(providers, 'Local Runtime')[0].models.map((entry) => entry.id)).toEqual([
      'local/small'
    ])
  })

  it('renders the selected model and its provider in the compact trigger', () => {
    const html = renderToStaticMarkup(
      <ModelPicker
        onChange={() => {}}
        providers={providers}
        value={{ provider: 'alpha', model: 'alpha/fast' }}
      />
    )
    expect(html).toContain('Fast')
    expect(html).toContain('Alpha Cloud')
    expect(html).toContain('aria-haspopup="listbox"')
  })

  it('keeps the provider default ahead of each reasoning model effort', () => {
    expect(modelEffortChoices(providers[0].models[0], 'Provider default')).toEqual([
      { value: '', label: 'Provider default' },
      { value: 'low', label: 'Low' },
      { value: 'high', label: 'High' }
    ])
    expect(
      modelEffortChoices({ ...providers[0].models[0], reasons: false }, 'Provider default')
    ).toEqual([])
  })
})
