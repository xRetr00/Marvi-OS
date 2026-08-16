import type { VoiceState } from '../store/voice-state'

const BARS = [0.35, 0.68, 0.92, 0.52, 0.78, 0.42, 0.88, 0.6, 0.3]

export function DynamicIsland({
  state,
  compact = false
}: {
  state: VoiceState
  compact?: boolean
}): React.JSX.Element {
  const active = state.phase !== 'ready'
  return (
    <div
      className={`dynamic-island island-${state.phase} ${compact ? 'island-compact' : ''}`}
      data-phase={state.phase}
    >
      <span className="island-orb" aria-hidden="true">
        M
      </span>
      <div className="island-copy">
        <small>{state.phase === 'ready' ? 'MARVI OS' : state.phase.toUpperCase()}</small>
        <strong>{state.caption}</strong>
      </div>
      <div className={active ? 'wave active' : 'wave'} aria-hidden="true">
        {BARS.map((bar, index) => (
          <i
            key={index}
            style={{ '--bar': bar, '--delay': `${index * -72}ms` } as React.CSSProperties}
          />
        ))}
      </div>
    </div>
  )
}
