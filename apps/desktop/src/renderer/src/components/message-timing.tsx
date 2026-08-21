import type { ComponentProps } from 'react'

import { AbstractIcon } from './abstract-icon'

export interface TimingStat {
  label: string
  value: string
}

/** Compact, reusable session telemetry adapted to Marvi's plain-CSS shell. */
export function MessageTiming({
  stats,
  streaming = false,
  className = '',
  ...props
}: Omit<ComponentProps<'div'>, 'children'> & {
  stats: readonly TimingStat[]
  streaming?: boolean
}): React.JSX.Element {
  return (
    <div
      data-slot="message-timing"
      className={`message-timing${streaming ? ' is-streaming' : ''}${className ? ` ${className}` : ''}`}
      {...props}
    >
      <AbstractIcon className="message-timing-icon" name="timing" size={14} />
      {stats.map((stat) => (
        <span className="message-timing-stat" key={stat.label}>
          <span className="message-timing-label">{stat.label}</span>
          <span className="message-timing-value">{stat.value}</span>
        </span>
      ))}
    </div>
  )
}
