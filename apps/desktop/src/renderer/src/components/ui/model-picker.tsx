import { Popover } from 'radix-ui'
import { Check, ChevronDown, Search } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import type { ModelCard, ModelProvider } from '../../../../shared/runtime'
import { haptic } from '../../lib/haptics'
import { modelContext, modelPrice } from '../model-labels'

export interface ModelSelection {
  model: string
  provider: string
}

interface ModelPickerProps {
  className?: string
  defaultOption?: { detail?: string; label: string }
  disabled?: boolean
  empty?: string
  onChange: (selection: ModelSelection | null) => void
  placeholder?: string
  providers: ModelProvider[]
  searchPlaceholder?: string
  side?: 'bottom' | 'left' | 'right' | 'top'
  value: ModelSelection | null
}

interface ModelRow {
  key: string
  model: ModelCard
  provider: ModelProvider
}

export interface ModelPickerGroup {
  models: ModelCard[]
  provider: ModelProvider
}

export function filterModelGroups(
  providers: ModelProvider[],
  query: string
): ModelPickerGroup[] {
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

/** One model catalog everywhere: compact trigger, provider groups, preserved
 * Gateway order, search across provider/name/id, and a visible current row. */
export function ModelPicker({
  className = '',
  defaultOption,
  disabled = false,
  empty = 'No models available.',
  onChange,
  placeholder = 'Choose a model',
  providers,
  searchPlaceholder = 'Search models…',
  side = 'bottom',
  value
}: ModelPickerProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(-1)
  const listRef = useRef<HTMLDivElement>(null)

  const selected = value
    ? providers
        .find((provider) => provider.provider === value.provider)
        ?.models.find((model) => model.id === value.model)
    : undefined

  const groups = useMemo(() => filterModelGroups(providers, query), [providers, query])

  const rows = useMemo<ModelRow[]>(
    () =>
      groups.flatMap(({ models, provider }) =>
        models.map((model) => ({
          key: `${provider.provider}::${model.id}`,
          model,
          provider
        }))
      ),
    [groups]
  )

  const showDefault = Boolean(
    defaultOption &&
      (!query ||
        `${defaultOption.label} ${defaultOption.detail ?? ''}`
          .toLowerCase()
          .includes(query.toLowerCase()))
  )
  const rowOffset = showDefault ? 1 : 0
  const choiceCount = rows.length + rowOffset
  const rowIndexes = useMemo(
    () => new Map(rows.map((row, index) => [row.key, index + rowOffset])),
    [rowOffset, rows]
  )

  useEffect(() => {
    if (!open) return
    const selectedIndex = value
      ? rows.findIndex(
          (row) => row.provider.provider === value.provider && row.model.id === value.model
        ) + rowOffset
      : showDefault
        ? 0
        : -1
    setActiveIndex(selectedIndex >= 0 ? selectedIndex : choiceCount > 0 ? 0 : -1)
  }, [choiceCount, open, rowOffset, rows, showDefault, value])

  useEffect(() => {
    if (activeIndex < 0) return
    listRef.current
      ?.querySelector<HTMLElement>(`[data-model-index="${activeIndex}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex])

  const choose = (selection: ModelSelection | null): void => {
    haptic('tap')
    onChange(selection)
    setOpen(false)
  }

  const chooseActive = (): void => {
    if (activeIndex < 0) return
    if (showDefault && activeIndex === 0) {
      choose(null)
      return
    }
    const row = rows[activeIndex - rowOffset]
    if (row) choose({ provider: row.provider.provider, model: row.model.id })
  }

  return (
    <Popover.Root
      open={open}
      onOpenChange={
        disabled
          ? undefined
          : (next) => {
              setOpen(next)
              if (!next) setQuery('')
            }
      }
    >
      <Popover.Trigger asChild>
        <button
          aria-expanded={open}
          aria-haspopup="listbox"
          className={`model-picker-trigger ${className}`}
          disabled={disabled}
          type="button"
        >
          <span className="model-picker-trigger-copy">
            <span className="model-picker-trigger-label">
              {selected?.name ?? (value ? value.model : defaultOption?.label) ?? placeholder}
            </span>
            {selected ? (
              <span className="model-picker-trigger-provider">
                {providers.find((provider) => provider.provider === value?.provider)?.label}
              </span>
            ) : null}
          </span>
          <ChevronDown aria-hidden="true" />
        </button>
      </Popover.Trigger>

      <Popover.Portal>
        <Popover.Content
          align="start"
          className="model-picker-panel"
          collisionPadding={12}
          side={side}
          sideOffset={8}
        >
          <div className="model-picker-search-wrap">
            <Search aria-hidden="true" />
            <input
              aria-activedescendant={activeIndex >= 0 ? `model-choice-${activeIndex}` : undefined}
              aria-label={searchPlaceholder}
              autoFocus
              className="model-picker-search"
              onChange={(event) => {
                setQuery(event.target.value)
                setActiveIndex(choiceCount > 0 ? 0 : -1)
              }}
              onKeyDown={(event) => {
                if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                  event.preventDefault()
                  if (choiceCount > 0) {
                    const delta = event.key === 'ArrowDown' ? 1 : -1
                    setActiveIndex((current) =>
                      current < 0 ? 0 : (current + delta + choiceCount) % choiceCount
                    )
                  }
                } else if (event.key === 'Enter') {
                  event.preventDefault()
                  chooseActive()
                }
              }}
              placeholder={searchPlaceholder}
              role="combobox"
              value={query}
            />
          </div>

          <div className="model-picker-list" ref={listRef} role="listbox">
            {defaultOption && showDefault ? (
              <button
                aria-selected={!value}
                className={`model-picker-row${!value ? ' is-selected' : ''}${activeIndex === 0 ? ' is-active' : ''}`}
                data-model-index="0"
                id="model-choice-0"
                onClick={() => choose(null)}
                onMouseEnter={() => setActiveIndex(0)}
                role="option"
                type="button"
              >
                <span className="model-picker-row-copy">
                  <strong>{defaultOption.label}</strong>
                  {defaultOption.detail ? <small>{defaultOption.detail}</small> : null}
                </span>
                {!value ? <Check aria-hidden="true" /> : null}
              </button>
            ) : null}

            {groups.map(({ models, provider }) => (
              <section className="model-picker-group" key={provider.provider}>
                <header className="model-picker-group-heading">
                  <strong>{provider.label}</strong>
                  <span>
                    {provider.provider} · {models.length}
                  </span>
                </header>
                {models.map((model) => {
                  const index = rowIndexes.get(`${provider.provider}::${model.id}`) ?? -1
                  const isSelected =
                    value?.provider === provider.provider && value.model === model.id
                  const hint = [modelContext(model.context), modelPrice(model)].filter(Boolean).join(' · ')
                  return (
                    <button
                      aria-selected={isSelected}
                      className={`model-picker-row${isSelected ? ' is-selected' : ''}${activeIndex === index ? ' is-active' : ''}`}
                      data-model-index={index}
                      id={`model-choice-${index}`}
                      key={model.id}
                      onClick={() => choose({ provider: provider.provider, model: model.id })}
                      onMouseEnter={() => setActiveIndex(index)}
                      role="option"
                      type="button"
                    >
                      <span className="model-picker-row-copy">
                        <strong>{model.name}</strong>
                        {model.id !== model.name ? <small>{model.id}</small> : null}
                      </span>
                      {hint ? <span className="model-picker-row-hint">{hint}</span> : null}
                      {isSelected ? <Check aria-hidden="true" /> : null}
                    </button>
                  )
                })}
              </section>
            ))}

            {groups.length === 0 && !showDefault ? (
              <p className="model-picker-empty">{query ? 'No matching models.' : empty}</p>
            ) : null}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
