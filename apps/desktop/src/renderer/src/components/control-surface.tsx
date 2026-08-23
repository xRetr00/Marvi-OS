import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'

type Tone = 'neutral' | 'ready' | 'warning' | 'danger' | 'accent'

export function ControlPage({
  children,
  className = '',
  description,
  title
}: {
  children: ReactNode
  className?: string
  description?: ReactNode
  title: string
}): React.JSX.Element {
  return (
    <section className={`control-page ${className}`.trim()}>
      <header className="control-page-head">
        <h2>{title}</h2>
        {description ? <p>{description}</p> : null}
      </header>
      <div className="control-page-body">{children}</div>
    </section>
  )
}

export function ControlSection({
  action,
  children,
  className = '',
  description,
  icon: Icon,
  title
}: {
  action?: ReactNode
  children: ReactNode
  className?: string
  description?: ReactNode
  icon?: LucideIcon
  title: string
}): React.JSX.Element {
  return (
    <section className={`control-section ${className}`.trim()}>
      <header className="control-section-head">
        <div className="control-section-title">
          {Icon ? <Icon aria-hidden="true" /> : null}
          <div>
            <h3>{title}</h3>
            {description ? <p>{description}</p> : null}
          </div>
        </div>
        {action ? <div className="control-section-action">{action}</div> : null}
      </header>
      <div className="control-section-body">{children}</div>
    </section>
  )
}

export function ControlRow({
  action,
  children,
  description,
  icon: Icon,
  title
}: {
  action?: ReactNode
  children?: ReactNode
  description?: ReactNode
  icon?: LucideIcon
  title: ReactNode
}): React.JSX.Element {
  return (
    <div className="control-row">
      <div className="control-row-copy">
        {Icon ? <Icon aria-hidden="true" /> : null}
        <div>
          <strong>{title}</strong>
          {description ? <p>{description}</p> : null}
          {children}
        </div>
      </div>
      {action ? <div className="control-row-action">{action}</div> : null}
    </div>
  )
}

export function ControlPill({
  children,
  tone = 'neutral'
}: {
  children: ReactNode
  tone?: Tone
}): React.JSX.Element {
  return <span className={`control-pill is-${tone}`}>{children}</span>
}

export function ControlEmpty({
  action,
  description,
  icon: Icon,
  title
}: {
  action?: ReactNode
  description: ReactNode
  icon?: LucideIcon
  title: string
}): React.JSX.Element {
  return (
    <div className="control-empty">
      {Icon ? <Icon aria-hidden="true" /> : null}
      <strong>{title}</strong>
      <p>{description}</p>
      {action}
    </div>
  )
}

export function ControlButton({
  children,
  className = '',
  destructive = false,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  destructive?: boolean
}): React.JSX.Element {
  return (
    <button
      className={`control-button${destructive ? ' is-destructive' : ''} ${className}`.trim()}
      type="button"
      {...props}
    >
      {children}
    </button>
  )
}
