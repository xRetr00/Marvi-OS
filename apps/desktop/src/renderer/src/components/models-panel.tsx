import { useEffect, useState } from 'react'
import { Brain, Route } from 'lucide-react'

import type { ModelCard, ModelProvider, ProviderPage, UpstreamPage } from '../../../shared/runtime'
import { ControlPage, ControlSection } from './control-surface'
import { Picker, type PickerOption } from './ui/picker'
import { ProcessingCard } from './ui/processing-card'

/**
 * Choosing a model, an effort, and — for a gateway — who serves it.
 *
 * One question at a time, in the order they depend on each other. It first
 * listed every configured provider at once, each with its own card and its own
 * model list, which repeated the Providers page and asked five questions to
 * answer one. A model list means nothing before a provider is chosen, so the
 * provider is the only question on screen until it has an answer.
 *
 * Models are fetched for the chosen provider, when it is chosen. Loading four
 * hundred OpenRouter models to fill a picker nobody opened is work nobody
 * asked for.
 *
 * Everything here writes an environment variable the registry already reads,
 * so nothing is stored twice and nothing is hard-coded in the UI.
 */

function contextLabel(tokens: number): string {
  if (!tokens) return ''
  return tokens >= 1000 ? `${Math.round(tokens / 1000)}K context` : `${tokens} context`
}

function price(model: ModelCard): string {
  // Null and zero are different: a free model is real, and a price the
  // provider never published must not read as free.
  if (model.promptPerMillion === null) return ''
  const output = model.completionPerMillion === null ? '' : ` / $${model.completionPerMillion}`
  return `$${model.promptPerMillion}${output} per M`
}

export function ModelsPanel(): React.JSX.Element {
  const [providers, setProviders] = useState<ProviderPage | null>(null)
  const [provider, setProvider] = useState('')
  const [catalog, setCatalog] = useState<ModelProvider | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let gone = false
    void (async () => {
      const page = await window.marvi?.getProviders()
      if (gone) return
      setProviders(page ?? null)
      setError(page ? '' : 'Marvi Gateway is unavailable.')
      // Open on whichever provider is already answering, so the page shows the
      // current arrangement rather than an empty form.
      if (page?.selected) setProvider(page.selected)
    })()
    return () => {
      gone = true
    }
  }, [])

  useEffect(() => {
    if (!provider) return
    let gone = false
    void (async () => {
      const page = await window.marvi?.getModels({ provider })
      if (gone) return
      setCatalog(page?.providers[0] ?? null)
    })()
    return () => {
      gone = true
    }
  }, [provider])

  // The catalog is only this provider's when it says so. Derived rather than
  // cleared on every change: clearing was a synchronous setState in an effect,
  // and it also let the previous provider's models show for a frame after
  // switching -- a list of models you cannot actually select.
  const active = catalog?.provider === provider ? catalog : null
  const loading = Boolean(provider) && active === null

  const connected = (providers?.providers ?? []).filter((row) => row.configured)
  const settings = providers?.settings ?? {}
  const row = providers?.providers.find((entry) => entry.name === provider)

  const model = settings[row?.env.model ?? ''] || active?.selected || ''
  const chosen = active?.models.find((entry) => entry.id === model)
  const effortEnv = row?.env.effort ?? ''

  const save = async (values: Record<string, string>): Promise<void> => {
    const next = await window.marvi?.setProviderSettings(values)
    if (next) setProviders(next)
    else setError('Could not save. The Gateway did not accept the change.')
  }

  return (
    <ControlPage
      description="Choose the provider, model, and reasoning effort used for new sessions."
      title="Models"
    >

      {!providers && !error ? (
        <ProcessingCard
          compact
          detail="Reading connected providers and the active model."
          title="Loading models"
        />
      ) : null}

      {error ? <p className="notice notice-warn">{error}</p> : null}

      {providers && connected.length === 0 ? (
        <p className="notice">
          No provider is connected yet. Open Providers, connect one, and its models will be listed
          here.
        </p>
      ) : null}

      <ControlSection icon={Brain} title="Default model">
      <div className="choice-flow">
        <div className="choice-row">
          <span className="choice-label">Provider</span>
          <Picker
            options={connected.map((entry) => ({
              value: entry.name,
              label: entry.label,
              detail: entry.accessPath === 'local' ? 'Runs on this machine' : undefined
            }))}
            value={provider}
            onChange={(next) => {
              setProvider(next)
              // The choice has to be written, not just held on the page.
              // MARVI_PROVIDER is what every caller reads to decide who
              // answers; without it the picker changed a model name for a
              // provider nothing was going to call, and turns fell through to
              // whichever local endpoint sorted first.
              void save({ MARVI_PROVIDER: next })
            }}
            placeholder="Choose a provider"
            searchPlaceholder="Search providers…"
            empty="No connected providers."
          />
        </div>

        <div className="choice-row">
          <span className="choice-label">
            Model
            <span className="choice-hint">
              {!provider
                ? 'Choose a provider first'
                : loading
                  ? 'Asking the provider…'
                  : active?.models.length
                    ? `${active.models.length} available`
                    : 'This provider listed none'}
            </span>
          </span>
          <Picker
            options={(active?.models ?? []).map((entry): PickerOption => ({
              value: entry.id,
              // The id under the name, because the id is what a provider
              // error quotes back and the name is what you recognise.
              label: entry.name,
              detail: entry.id === entry.name ? undefined : entry.id,
              hint: [contextLabel(entry.context), price(entry)].filter(Boolean).join('  ')
            }))}
            value={model}
            onChange={(next) => {
              if (row?.env.model) void save({ [row.env.model]: next })
            }}
            placeholder={model || 'Choose a model'}
            searchPlaceholder="Search models…"
            empty="This provider listed no models."
            disabled={!provider || loading || !active?.models.length}
          />
        </div>

        <div className="choice-row">
          <span className="choice-label">
            Effort
            <span className="choice-hint">
              {!chosen
                ? 'Choose a model first'
                : chosen.reasons
                  ? 'How long it thinks before answering'
                  : 'This model does not reason'}
            </span>
          </span>
          <Picker
            options={[
              { value: '', label: 'Provider default' },
              ...(chosen?.efforts ?? []).map((level) => ({
                value: level,
                label: level.charAt(0).toUpperCase() + level.slice(1)
              }))
            ]}
            value={settings[effortEnv] ?? ''}
            onChange={(next) => {
              if (effortEnv) void save({ [effortEnv]: next })
            }}
            placeholder="Provider default"
            disabled={!chosen?.reasons || !effortEnv}
          />
        </div>

      </div>
      </ControlSection>

      {active?.routesUpstream ? (
        <ControlSection icon={Route} title="Routing">
          <div className="choice-flow">
            <UpstreamChoice model={model} onSave={save} />
          </div>
        </ControlSection>
      ) : null}

      {loading ? (
        <ProcessingCard
          compact
          detail={`${row?.label ?? 'Provider'} is returning its current model catalog.`}
          title="Fetching model catalog"
        />
      ) : null}

      {active && !active.reachable ? (
        <p className="notice notice-warn">
          {active.label} is configured but returned no models. Its credential may be wrong, or its
          API may not be reachable from this machine.
        </p>
      ) : null}
    </ControlPage>
  )
}

/**
 * Who actually serves an OpenRouter model.
 *
 * OpenRouter is a marketplace, not a host: one model name, several upstreams,
 * different prices and different speeds. Its own default takes the cheapest
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
    if (!model) return
    let gone = false
    void (async () => {
      const next = await window.marvi?.getUpstreams(model)
      if (!gone) setPage(next ?? null)
    })()
    return () => {
      gone = true
    }
  }, [model])

  const upstreams = page?.upstreams ?? []

  return (
    <>
      <div className="choice-row">
        <span className="choice-label">
          Routing policy
          <span className="choice-hint">Resolved per request against live numbers</span>
        </span>
        <Picker
          options={(page?.policies ?? ['auto', 'cheapest', 'fastest', 'throughput']).map(
            (name) => ({
              value: name === 'auto' ? '' : name,
              label: name.charAt(0).toUpperCase() + name.slice(1),
              detail:
                name === 'fastest'
                  ? 'Best for voice — first-token time is the whole experience'
                  : name === 'cheapest'
                    ? "OpenRouter's own default"
                    : undefined
            })
          )}
          value={policy}
          onChange={(next) => {
            setPolicy(next)
            void onSave({ MARVI_OPENROUTER_ROUTE: next })
          }}
          placeholder="Auto — OpenRouter decides"
          disabled={!model}
        />
      </div>

      <div className="choice-row">
        <span className="choice-label">
          Preferred provider
          <span className="choice-hint">
            {upstreams.length ? `${upstreams.length} can serve this model` : 'Optional'}
          </span>
        </span>
        <Picker
          options={[
            { value: '', label: 'No preference' },
            ...upstreams.map((upstream) => ({
              value: upstream.slug,
              label: upstream.name,
              detail: [
                upstream.quantization,
                contextLabel(upstream.context),
                // Usually absent. OpenRouter publishes latency per endpoint and
                // leaves most unset, so this says so rather than showing a zero
                // that reads as instant.
                upstream.latencyMs === null ? 'latency unpublished' : `${upstream.latencyMs} ms`
              ]
                .filter(Boolean)
                .join(' · '),
              hint: upstream.promptPerMillion === null ? '' : `$${upstream.promptPerMillion} per M`
            }))
          ]}
          value={pinned}
          onChange={(next) => {
            setPinned(next)
            void onSave({ MARVI_OPENROUTER_PROVIDERS: next })
          }}
          placeholder="No preference"
          searchPlaceholder="Search providers…"
          empty="OpenRouter listed no upstreams for this model."
          disabled={!model || upstreams.length === 0}
        />
      </div>
    </>
  )
}
