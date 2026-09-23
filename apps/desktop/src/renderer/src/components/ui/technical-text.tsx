import type { ReactNode } from 'react'

/** Keep a Latin path, URL, model name, or identifier intact inside RTL prose. */
export function TechnicalText({
  children,
  className,
  title
}: {
  children: ReactNode
  className?: string
  title?: string
}): React.JSX.Element {
  return <bdi className={className} dir="ltr" title={title}>{children}</bdi>
}
