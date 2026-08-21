import type { ReactElement, ReactNode } from 'react'
import { Tooltip as RadixTooltip } from 'radix-ui'

export function TooltipProvider({ children }: { children: ReactNode }): React.JSX.Element {
  return (
    <RadixTooltip.Provider delayDuration={320} skipDelayDuration={80}>
      {children}
    </RadixTooltip.Provider>
  )
}

export function UiTooltip({
  children,
  label,
  side = 'top'
}: {
  children: ReactElement
  label: string
  side?: 'top' | 'right' | 'bottom' | 'left'
}): React.JSX.Element {
  return (
    <RadixTooltip.Root>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content className="ui-tooltip" side={side} sideOffset={8}>
          <span className="ui-tooltip-index" aria-hidden="true">
            +
          </span>
          {label}
          <RadixTooltip.Arrow className="ui-tooltip-arrow" />
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  )
}
