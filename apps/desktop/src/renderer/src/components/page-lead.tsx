import { AbstractIcon, type AbstractIconName } from './abstract-icon'

export function PageLead({
  description,
  icon,
  label,
  title
}: {
  description: string
  icon: AbstractIconName
  label?: string
  title: string
}): React.JSX.Element {
  return (
    <header className="page-lead-card">
      <span className="page-lead-icon">
        <AbstractIcon name={icon} size={22} />
      </span>
      <div>
        <span className="page-lead-label">{label ?? `// ${title.toUpperCase()}`}</span>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
    </header>
  )
}
