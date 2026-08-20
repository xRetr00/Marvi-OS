import { Popover } from 'radix-ui'
import { useEffect, useMemo, useRef, useState } from 'react'

import { haptic } from '../../lib/haptics'

/**
 * A searchable dropdown for things there are too many of to scroll.
 *
 * Marvi has three lists with the same problem and the same shape: models a
 * provider offers (hundreds, on OpenRouter), the upstreams that can serve one,
 * and the voices that are downloaded. All three were text boxes, which is a
 * guess with no feedback — a typo and a name that no longer exists fail
 * identically, and both fail later.
 *
 * `preview` is what makes it worth one component rather than three: a voice is
 * the one option you cannot judge by reading, so its row plays.
 *
 * Built on the Radix Popover already in the app rather than adding a combobox
 * dependency; the filtering is a substring match, which is the right amount of
 * cleverness for a list you can see all of.
 */
export interface PickerOption {
  value: string
  label: string
  /** Second line — the model id under its display name, an accent, a slug. */
  detail?: string
  /** Right-aligned metadata: a price, a context window, a latency. */
  hint?: string
  /** An audio URL. Rows that have one get a play button. */
  preview?: string
  disabled?: boolean
}

export function Picker({
  options,
  value,
  onChange,
  placeholder = 'Select…',
  searchPlaceholder = 'Search…',
  empty = 'Nothing to choose from.',
  disabled = false,
  className = ''
}: {
  options: PickerOption[]
  value: string
  onChange: (value: string) => void
  placeholder?: string
  searchPlaceholder?: string
  empty?: string
  disabled?: boolean
  className?: string
}): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')

  const selected = options.find((option) => option.value === value)

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return options
    return options.filter((option) =>
      `${option.label} ${option.detail ?? ''} ${option.value}`.toLowerCase().includes(needle)
    )
  }, [options, query])

  return (
    <Popover.Root
      open={open}
      onOpenChange={
        disabled
          ? undefined
          : (next) => {
              setOpen(next)
              // Cleared as it closes, not in an effect watching `open`.
              // Reopening a list you filtered earlier and finding your old
              // search still in it reads as the app being stuck.
              if (!next) setQuery('')
            }
      }
    >
      <Popover.Trigger asChild>
        <button
          type="button"
          className={`picker-trigger ${className}`}
          disabled={disabled}
          aria-expanded={open}
        >
          <span className="picker-value">
            {selected ? selected.label : <span className="picker-placeholder">{placeholder}</span>}
          </span>
          <span className="picker-caret" aria-hidden="true">
            ▾
          </span>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className="picker-panel" sideOffset={4} align="start">
          <input
            className="picker-search"
            placeholder={searchPlaceholder}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            autoFocus
          />
          <div className="picker-list" role="listbox">
            {shown.length === 0 ? (
              <div className="picker-empty">{query ? 'No match.' : empty}</div>
            ) : (
              shown.map((option) => (
                <PickerRow
                  key={option.value}
                  option={option}
                  selected={option.value === value}
                  onSelect={() => {
                    haptic('tap')
                    onChange(option.value)
                    setOpen(false)
                  }}
                />
              ))
            )}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}

function PickerRow({
  option,
  selected,
  onSelect
}: {
  option: PickerOption
  selected: boolean
  onSelect: () => void
}): React.JSX.Element {
  const [playing, setPlaying] = useState(false)
  const audio = useRef<HTMLAudioElement | null>(null)

  useEffect(
    () => () => {
      audio.current?.pause()
      audio.current = null
    },
    []
  )

  const togglePreview = (event: React.MouseEvent): void => {
    // Stops the row from being chosen: hearing a voice and picking it are
    // separate decisions, and one should not force the other.
    event.preventDefault()
    event.stopPropagation()
    if (!option.preview) return
    if (playing) {
      audio.current?.pause()
      setPlaying(false)
      return
    }
    const player = new Audio(option.preview)
    player.onended = () => setPlaying(false)
    player.onerror = () => setPlaying(false)
    audio.current = player
    setPlaying(true)
    void player.play().catch(() => setPlaying(false))
  }

  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      className={`picker-row${selected ? ' is-selected' : ''}`}
      disabled={option.disabled}
      onClick={onSelect}
    >
      {option.preview ? (
        <span
          className={`picker-preview${playing ? ' is-playing' : ''}`}
          onClick={togglePreview}
          role="button"
          tabIndex={-1}
          aria-label={playing ? 'Stop preview' : 'Play preview'}
        >
          {playing ? '❚❚' : '▶'}
        </span>
      ) : null}
      <span className="picker-row-text">
        <span className="picker-row-label">{option.label}</span>
        {option.detail ? <span className="picker-row-detail">{option.detail}</span> : null}
      </span>
      {option.hint ? <span className="picker-row-hint">{option.hint}</span> : null}
      <span className="picker-check" aria-hidden="true">
        {selected ? '✓' : ''}
      </span>
    </button>
  )
}
