import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { ModelCard, ModelProvider } from '../../../../shared/runtime'
import { ModelBrandLogo } from './model-brand-logo'
import { ModelPicker } from './model-picker'
import {
  filterModelGroups,
  modelBrandKey,
  modelBrandMonogram,
  modelEffortChoices,
  modelEffortLabel
} from './model-picker-utils'

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
    expect(
      filterModelGroups(providers, 'Local Runtime')[0].models.map((entry) => entry.id)
    ).toEqual(['local/small'])
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

  it('keeps the selected reasoning effort visible after the menu closes', () => {
    const html = renderToStaticMarkup(
      <ModelPicker
        effort="xhigh"
        effortDefaultLabel="Provider default"
        onChange={() => {}}
        providers={providers}
        value={{ provider: 'alpha', model: 'alpha/fast' }}
      />
    )

    expect(html).toContain('Alpha Cloud · XHigh')
  })

  it('shows the actual configured model instead of masking it behind the default label', () => {
    const html = renderToStaticMarkup(
      <ModelPicker
        defaultOption={{
          label: 'Default model',
          detail: 'Fast · Alpha Cloud',
          selection: { provider: 'alpha', model: 'alpha/fast' }
        }}
        onChange={() => {}}
        providers={providers}
        value={null}
      />
    )
    expect(html).toContain('Fast')
    expect(html).toContain('Default · Alpha Cloud')
  })

  it('uses the model owner for aggregated catalogs and falls back to a compact monogram', () => {
    expect(modelBrandKey('anthropic/claude-sonnet', 'openrouter')).toBe('anthropic')
    expect(modelBrandKey('meta-llama/llama-4', 'openrouter')).toBe('meta')
    expect(modelBrandKey('gpt-5', 'openai')).toBe('openai')
    expect(modelBrandMonogram('unknown-labs')).toBe('UL')

    const html = renderToStaticMarkup(
      <ModelBrandLogo
        label="Claude Sonnet"
        modelId="anthropic/claude-sonnet"
        provider="openrouter"
      />
    )
    expect(html).toContain('<svg')
    expect(html).toContain('title="anthropic"')
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

  it('names a supported disabled reasoning mode as Off', () => {
    expect(modelEffortLabel('none', 'Provider default')).toBe('Off')
    expect(modelEffortLabel('off', 'Provider default')).toBe('Off')
    expect(modelEffortLabel('on', 'Provider default')).toBe('On')
  })
})
