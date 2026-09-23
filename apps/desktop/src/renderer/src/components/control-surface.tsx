import type { ComponentType, ReactNode, SVGProps } from 'react'
import type { LucideIcon } from 'lucide-react'
import { useStore } from '@nanostores/react'
import { $interfaceLocale, t } from '../store/locale'
import type { InterfaceLocale } from '../store/locale'

function localized(node: ReactNode, locale: InterfaceLocale): ReactNode {
  return typeof node === 'string' ? t(node, locale) : node
}

/** A Lucide glyph, or a brand mark from `@thesvg/react` where the real logo matters. */
type SectionIcon = LucideIcon | ComponentType<SVGProps<SVGSVGElement>>

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
  const locale = useStore($interfaceLocale)
  return (
    <section className={`control-page ${className}`.trim()}>
      <header className="control-page-head">
        <h2>{t(title, locale)}</h2>
        {description ? <p>{localized(description, locale)}</p> : null}
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
  icon?: SectionIcon
  title: string
}): React.JSX.Element {
  const locale = useStore($interfaceLocale)
  return (
    <section className={`control-section ${className}`.trim()}>
      <header className="control-section-head">
        <div className="control-section-title">
          {Icon ? <Icon aria-hidden="true" /> : null}
          <div>
            <h3>{t(title, locale)}</h3>
            {description ? <p>{localized(description, locale)}</p> : null}
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
  const locale = useStore($interfaceLocale)
  return (
    <div className="control-row">
      <div className="control-row-copy">
        {Icon ? <Icon aria-hidden="true" /> : null}
        <div>
          <strong>{localized(title, locale)}</strong>
          {description ? <p>{localized(description, locale)}</p> : null}
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
  const locale = useStore($interfaceLocale)
  return <span className={`control-pill is-${tone}`}>{localized(children, locale)}</span>
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
  const locale = useStore($interfaceLocale)
  return (
    <div className="control-empty">
      {Icon ? <Icon aria-hidden="true" /> : null}
      <strong>{t(title, locale)}</strong>
      <p>{localized(description, locale)}</p>
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
  const locale = useStore($interfaceLocale)
  return (
    <button
      className={`control-button${destructive ? ' is-destructive' : ''} ${className}`.trim()}
      type="button"
      {...props}
    >
      {localized(children, locale)}
    </button>
  )
}
