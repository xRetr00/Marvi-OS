import { useCallback, useEffect, useState } from 'react'

import type {
  ModelCard,
  ModelPage,
  ModelProvider,
  ProviderPage,
  UpstreamPage
} from '../../../shared/runtime'
import { AsciiRule } from './ui/ascii-rule'
import { Picker, type PickerOption } from './ui/picker'

/**
 * Choosing a model, an effort, and — for a gateway — who serves it.
 *
 * Split from Providers because they answer different questions. Providers is
 * "can Marvi reach this at all": credentials, sign-in, spend. This is "what
 * should it use", which you change far more often and which has nothing to do
 * with a key.
 *
 * Everything here writes an environment variable the registry already reads,
 * so nothing is stored twice and nothing is hard-coded in the UI.
 */

function price(model: ModelCard): string {
  // Null and zero are different: a free model is real, and a price the
  // provider never published must not read as free.
  if (model.promptPerMillion === null) return ''
  const input = `$${model.promptPerMillion}`
  const output = model.completionPerMillion === null ? '' : ` / $${model.completionPerMillion}`
  return `${input}${output} per M`
}

function contextLabel(tokens: number): string {
  if (!tokens) return ''
  return tokens >= 1000 ? `${Math.round(tokens / 1000)}K ctx` : `${tokens} ctx`
}

function modelOptions(models: ModelCard[]): PickerOption[] {
  return models.map((model) => ({
    value: model.id,
    label: model.name,
    // The id under the display name, because the id is what a provider error
    // will name and the display name is what you recognise.
    detail: model.id === model.name ? undefined : model.id,
    hint: [contextLabel(model.context), price(model)].filter(Boolean).join('  ')
  }))
}

export function ModelsPanel(): React.JSX.Element {
  const [page, setPage] = useState<ModelPage | null>(null)
  const [providers, setProviders] = useState<ProviderPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async (refresh = false): Promise<void> => {
    setLoading(true)
    const [models, page] = await Promise.all([
      window.marvi?.getModels({ refresh }),
      window.marvi?.getProviders()
    ])
    setPage(models ?? null)
    setProviders(page ?? null)
    setError(models ? '' : 'Marvi Gateway is unavailable')
    setLoading(false)
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const save = async (values: Record<string, string>): Promise<void> => {
    const next = await window.marvi?.setProviderSettings(values)
    if (next) setProviders(next)
    else setError('Could not save; the Gateway did not accept the change')
  }

  const rows = page?.providers ?? []

  return (
    <section className="single-page panel">
      <div className="panel-label">{'// MODELS'}</div>
      <h2>Models</h2>
      <p>
        Every list here is what the provider says it has, asked when this page opened rather than
        typed from memory. Effort appears only on models that reason — the rest ignore it, and a
        control that does nothing is worse than no control.
      </p>

      <div className="context-line">
        <span>CATALOG</span>
        <button className="phase" type="button" onClick={() => void load(true)} disabled={loading}>
          {loading ? 'LOADING…' : 'REFRESH'}
        </button>
      </div>

      <AsciiRule />

      {error ? <span className="construction">{error.toUpperCase()}</span> : null}

      {!loading && rows.length === 0 && !error ? (
        <p className="construction">
          NO PROVIDER IS CONNECTED. OPEN PROVIDERS AND CONNECT ONE FIRST.
        </p>
      ) : null}

      <div className="service-list">
        {rows.map((row) => (
          <ProviderModels
            key={row.provider}
            row={row}
            effortEnv={
              providers?.providers.find((p) => p.name === row.provider)?.env.effort ?? ''
            }
            modelEnv={providers?.providers.find((p) => p.name === row.provider)?.env.model ?? ''}
            settings={providers?.settings ?? {}}
            onSave={save}
          />
        ))}
      </div>
    </section>
  )
}

function ProviderModels({
  row,
  modelEnv,
  effortEnv,
  settings,
  onSave
}: {
  row: ModelProvider
  modelEnv: string
  effortEnv: string
  settings: Record<string, string>
  onSave: (values: Record<string, string>) => Promise<void>
}): React.JSX.Element {
  const [model, setModel] = useState(row.selected)
  const chosen = row.models.find((entry) => entry.id === model)
  const effort = settings[effortEnv] ?? ''

  const choose = async (next: string): Promise<void> => {
    setModel(next)
    if (modelEnv) await onSave({ [modelEnv]: next })
  }

  return (
    <div className="service-card">
      <div className="service-head">
        <strong>{row.label}</strong>
        <span className="panel-label">
          {row.reachable ? `${row.models.length} MODELS` : 'LISTED NOTHING'}
        </span>
      </div>

      {!row.reachable ? (
        <p className="construction">
          THIS PROVIDER IS CONFIGURED BUT RETURNED NO MODELS. THE KEY MAY BE WRONG, OR ITS API MAY
          BE UNREACHABLE FROM HERE.
        </p>
      ) : null}

      <label className="field">
        <span className="panel-label">{'// MODEL'}</span>
        <Picker
          options={modelOptions(row.models)}
          value={model}
          onChange={(next) => void choose(next)}
          placeholder={row.selected || 'Choose a model'}
          searchPlaceholder="Search models…"
          empty="This provider listed no models."
          disabled={!row.reachable}
        />
      </label>

      {chosen?.reasons && effortEnv ? (
        <label className="field">
          <span className="panel-label">{'// EFFORT'}</span>
          <Picker
            options={[
              { value: '', label: 'Provider default' },
              ...chosen.efforts.map((level) => ({
                value: level,
                label: level.charAt(0).toUpperCase() + level.slice(1)
              }))
            ]}
            value={effort}
            onChange={(next) => void onSave({ [effortEnv]: next })}
            placeholder="Provider default"
          />
        </label>
      ) : null}

      {row.routesUpstream ? <UpstreamChoice model={model} onSave={onSave} /> : null}
    </div>
  )
}

/**
 * Who actually serves an OpenRouter model.
 *
 * OpenRouter is a marketplace, not a host: one model name, several upstreams,
 * different prices and different speeds. Its default picks the cheapest
 * reliable one, which is the wrong default for voice — first-token time is the
 * whole experience of a spoken turn.
 */
function UpstreamChoice({
  model,
  onSave
}: {
  model: string
  onSave: (values: Record<string, string>) => Promise<void>
}): React.JSX.Element {
  const [page, setPage] = useState<UpstreamPage | null>(null)
  const [policy, setPolicy] = useState('')
  const [pinned, setPinned] = useState('')

  useEffect(() => {
    let disposed = false
    void (async () => {
      const next = await window.marvi?.getUpstreams(model)
      if (!disposed) setPage(next ?? null)
    })()
    return () => {
      disposed = true
    }
  }, [model])

  const upstreams = page?.upstreams ?? []

  return (
    <>
      <label className="field">
        <span className="panel-label">{'// ROUTING'}</span>
        <Picker
          options={(page?.policies ?? ['auto', 'cheapest', 'fastest', 'throughput']).map((name) => ({
            value: name === 'auto' ? '' : name,
            label: name.charAt(0).toUpperCase() + name.slice(1),
            detail:
              name === 'fastest'
                ? 'Resolved per request, against numbers OpenRouter measures'
                : undefined
          }))}
          value={policy}
          onChange={(next) => {
            setPolicy(next)
            void onSave({ MARVI_OPENROUTER_ROUTE: next })
          }}
          placeholder="Auto — OpenRouter decides"
        />
      </label>

      <label className="field">
        <span className="panel-label">{'// PREFER ONE PROVIDER'}</span>
        <Picker
          options={[
            { value: '', label: 'No preference' },
            ...upstreams.map((upstream) => ({
              value: upstream.slug,
              label: upstream.name,
              detail: [
                upstream.quantization,
                contextLabel(upstream.context),
                // Usually absent. OpenRouter publishes latency per endpoint
                // and leaves most unset, so this says so rather than showing
                // a zero that reads as instant.
                upstream.latencyMs === null ? 'latency unpublished' : `${upstream.latencyMs} ms`
              ]
                .filter(Boolean)
                .join(' · '),
              hint:
                upstream.promptPerMillion === null ? '' : `$${upstream.promptPerMillion} per M`
            }))
          ]}
          value={pinned}
          onChange={(next) => {
            setPinned(next)
            void onSave({ MARVI_OPENROUTER_PROVIDERS: next })
          }}
          placeholder="No preference"
          empty="OpenRouter listed no upstreams for this model."
          searchPlaceholder="Search providers…"
        />
      </label>
    </>
  )
}
