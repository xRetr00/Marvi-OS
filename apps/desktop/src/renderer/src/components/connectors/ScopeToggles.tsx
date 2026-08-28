/**
 * Read/write/admin capability toggle, styled after the three-button group
 * Marvi's older Accounts settings page already used (`.account-scope`) rather
 * than openhuman's switch list — same idea (a single active scope gates which
 * curated tools the agent may call), Marvi's own button-group presentation.
 */
export function ScopeToggles({
  scope,
  disabled,
  onChange
}: {
  scope: 'read' | 'write' | 'admin'
  disabled: boolean
  onChange: (next: 'read' | 'write' | 'admin') => void
}): React.JSX.Element {
  return (
    <div aria-label="Connector capability" className="connector-scope" role="group">
      {(['read', 'write', 'admin'] as const).map((option) => (
        <button
          aria-pressed={scope === option}
          disabled={disabled}
          key={option}
          onClick={() => onChange(option)}
          type="button"
        >
          {option}
        </button>
      ))}
    </div>
  )
}
