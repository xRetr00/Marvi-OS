import { Popover } from 'radix-ui'
import { Check, ChevronDown, ChevronRight, Search } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import type { ModelCard, ModelProvider } from '../../../../shared/runtime'
import { haptic } from '../../lib/haptics'
import { modelContext, modelPrice } from '../model-labels'
import { ModelBrandLogo } from './model-brand-logo'
import { filterModelGroups, modelEffortChoices, modelEffortLabel } from './model-picker-utils'

export interface ModelSelection {
  model: string
  provider: string
}

interface ModelPickerProps {
  className?: string
  defaultOption?: { detail?: string; label: string; selection?: ModelSelection }
  disabled?: boolean
  empty?: string
  effort?: string
  effortDefaultLabel?: string
  onChange: (selection: ModelSelection | null, options?: { effort: string }) => void
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

/** One model catalog everywhere: compact trigger, provider groups, preserved
 * Gateway order, search across provider/name/id, and a visible current row. */
export function ModelPicker({
  className = '',
  defaultOption,
  disabled = false,
  empty = 'No models available.',
  effort = '',
  effortDefaultLabel = 'Default effort',
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

  const selectedProvider = value
    ? providers.find((provider) => provider.provider === value.provider)
    : undefined
  const selected = selectedProvider?.models.find((model) => model.id === value?.model)
  const defaultProvider = defaultOption?.selection
    ? providers.find((provider) => provider.provider === defaultOption.selection?.provider)
    : undefined
  const defaultModel = defaultProvider?.models.find(
    (model) => model.id === defaultOption?.selection?.model
  )

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

  const chooseEffort = (row: ModelRow, nextEffort: string): void => {
    haptic('tap')
    onChange({ provider: row.provider.provider, model: row.model.id }, { effort: nextEffort })
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
              if (next) {
                const selectedIndex = value
                  ? (rowIndexes.get(`${value.provider}::${value.model}`) ?? -1)
                  : showDefault
                    ? 0
                    : -1
                setActiveIndex(selectedIndex >= 0 ? selectedIndex : choiceCount > 0 ? 0 : -1)
              } else {
                setQuery('')
              }
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
          {selected || defaultOption?.selection ? (
            <ModelBrandLogo
              className="model-picker-trigger-brand"
              label={selected?.name ?? defaultOption?.detail ?? defaultOption?.label ?? placeholder}
              modelId={selected?.id ?? defaultOption?.selection?.model ?? ''}
              provider={selectedProvider?.provider ?? defaultOption?.selection?.provider ?? ''}
            />
          ) : null}
          <span className="model-picker-trigger-copy">
            <span className="model-picker-trigger-label">
              {selected?.name ??
                defaultModel?.name ??
                defaultOption?.selection?.model ??
                (value ? value.model : defaultOption?.label) ??
                placeholder}
            </span>
            {selected || defaultOption?.detail ? (
              <span className="model-picker-trigger-provider">
                {selected
                  ? `${selectedProvider?.label ?? selected.provider}${
                      selected.reasons
                        ? ` · ${modelEffortLabel(effort, effortDefaultLabel)}`
                        : ''
                    }`
                  : defaultProvider
                    ? `Default · ${defaultProvider.label}`
                    : defaultOption?.detail}
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
                const nextQuery = event.target.value
                const nextHasDefault = Boolean(
                  defaultOption &&
                  `${defaultOption.label} ${defaultOption.detail ?? ''}`
                    .toLowerCase()
                    .includes(nextQuery.toLowerCase())
                )
                const nextCount = filterModelGroups(providers, nextQuery).reduce(
                  (count, group) => count + group.models.length,
                  nextHasDefault ? 1 : 0
                )
                setQuery(nextQuery)
                setActiveIndex(nextCount > 0 ? 0 : -1)
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
                {defaultOption.selection ? (
                  <ModelBrandLogo
                    label={defaultModel?.name ?? defaultOption.detail ?? defaultOption.label}
                    modelId={defaultOption.selection.model}
                    provider={defaultOption.selection.provider}
                  />
                ) : null}
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
                  const hint = [modelContext(model.context), modelPrice(model)]
                    .filter(Boolean)
                    .join(' · ')
                  const row = rows[index - rowOffset]
                  return (
                    <ModelOption
                      active={activeIndex === index}
                      effort={isSelected ? effort : ''}
                      effortDefaultLabel={effortDefaultLabel}
                      hint={hint}
                      index={index}
                      key={model.id}
                      model={model}
                      onChoose={() => choose({ provider: provider.provider, model: model.id })}
                      onChooseEffort={(nextEffort) => {
                        if (row) chooseEffort(row, nextEffort)
                      }}
                      onHover={() => setActiveIndex(index)}
                      provider={provider.provider}
                      selected={isSelected}
                    />
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

interface ModelOptionProps {
  active: boolean
  effort: string
  effortDefaultLabel: string
  hint: string
  index: number
  model: ModelCard
  onChoose: () => void
  onChooseEffort: (effort: string) => void
  onHover: () => void
  provider: string
  selected: boolean
}

function ModelOption({
  active,
  effort,
  effortDefaultLabel,
  hint,
  index,
  model,
  onChoose,
  onChooseEffort,
  onHover,
  provider,
  selected
}: ModelOptionProps): React.JSX.Element {
  const [optionsOpen, setOptionsOpen] = useState(false)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const keepOpen = (): void => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    setOptionsOpen(true)
  }
  const closeSoon = (): void => {
    if (closeTimer.current) clearTimeout(closeTimer.current)
    closeTimer.current = setTimeout(() => setOptionsOpen(false), 120)
  }

  useEffect(
    () => () => {
      if (closeTimer.current) clearTimeout(closeTimer.current)
    },
    []
  )

  return (
    <div className="model-picker-option" onMouseEnter={keepOpen} onMouseLeave={closeSoon}>
      <button
        aria-selected={selected}
        className={`model-picker-row${selected ? ' is-selected' : ''}${active ? ' is-active' : ''}`}
        data-model-index={index}
        id={`model-choice-${index}`}
        onClick={onChoose}
        onMouseEnter={onHover}
        role="option"
        type="button"
      >
        <ModelBrandLogo label={model.name} modelId={model.id} provider={provider} />
        <span className="model-picker-row-copy">
          <strong>{model.name}</strong>
          {model.id !== model.name ? <small>{model.id}</small> : null}
        </span>
        {hint ? <span className="model-picker-row-hint">{hint}</span> : null}
        {model.reasons ? (
          <span className="model-picker-row-effort">
            {modelEffortLabel(effort, effortDefaultLabel)}
          </span>
        ) : null}
        {selected ? <Check aria-hidden="true" /> : null}
      </button>

      {model.reasons ? (
        <Popover.Root modal={false} onOpenChange={setOptionsOpen} open={optionsOpen}>
          <Popover.Trigger asChild>
            <button
              aria-label={`Reasoning effort for ${model.name}`}
              className="model-picker-effort-trigger"
              onFocus={keepOpen}
              onMouseEnter={keepOpen}
              type="button"
            >
              <ChevronRight aria-hidden="true" />
            </button>
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Content
              align="start"
              className="model-picker-effort-panel"
              collisionPadding={12}
              onMouseEnter={keepOpen}
              onMouseLeave={closeSoon}
              side="right"
              sideOffset={5}
            >
              <header>
                <small>Model options</small>
                <strong>{model.name}</strong>
              </header>
              <span className="model-picker-effort-heading">Reasoning effort</span>
              {modelEffortChoices(model, effortDefaultLabel).map((choice) => {
                const checked = effort === choice.value
                return (
                  <button
                    className={checked ? 'is-selected' : ''}
                    key={choice.value || 'default'}
                    onClick={() => onChooseEffort(choice.value)}
                    type="button"
                  >
                    <span>{choice.label}</span>
                    {checked ? <Check aria-hidden="true" /> : null}
                  </button>
                )
              })}
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
      ) : null}
    </div>
  )
}
