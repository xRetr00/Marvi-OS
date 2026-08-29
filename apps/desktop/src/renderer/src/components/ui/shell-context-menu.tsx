/**
 * Shell context menu — right-click on chrome that owns no menu of its own
 * (title bar gutter, sidebar background, empty panel body) gets window-level
 * verbs instead of nothing. Adapted from the the predecessor assistant desktop
 * ShellContextMenu pattern (MIT): a fallback wrapper, where surfaces with
 * their own menu stopPropagation before the trigger sees the event.
 * Provenance: the predecessor assistant\apps\desktop\src\app\shell\shell-context-menu.tsx
 * and components/ui/context-menu.tsx (see docs/UPSTREAM.md).
 */
import { ContextMenu } from 'radix-ui'
import { cloneElement, Fragment, useState, type ReactElement } from 'react'
import { flushSync } from 'react-dom'
import type { LucideIcon } from 'lucide-react'

import { haptic } from '../../lib/haptics'

export interface ShellMenuAction {
  label: string
  onSelect: () => void
  disabled?: boolean
  icon?: LucideIcon
  separatorBefore?: boolean
  tone?: 'default' | 'danger'
}

export type ShellMenuSurface = 'page' | 'settings' | 'sidebar' | 'statusbar' | 'titlebar'

interface ShellContextMenuProps {
  children: ReactElement
  actions: ShellMenuAction[] | ((surface: ShellMenuSurface) => ShellMenuAction[])
}

export function ShellContextMenu({ actions, children }: ShellContextMenuProps): React.JSX.Element {
  const [surface, setSurface] = useState<ShellMenuSurface>('page')
  const visibleActions = typeof actions === 'function' ? actions(surface) : actions
  const trigger = cloneElement(children, {
    onContextMenuCapture: (event: React.MouseEvent<HTMLElement>) => {
      const target = event.target as HTMLElement
      const owner = target.closest<HTMLElement>('[data-shell-context]')
      const next = (owner?.dataset.shellContext as ShellMenuSurface | undefined) ?? 'page'
      flushSync(() => setSurface(next))
    }
  } as React.HTMLAttributes<HTMLElement>)

  return (
    <ContextMenu.Root>
      <ContextMenu.Trigger asChild>{trigger}</ContextMenu.Trigger>
      <ContextMenu.Portal>
        <ContextMenu.Content className="shell-context-menu">
          {visibleActions.map((action) => {
            const Icon = action.icon
            return (
              <Fragment key={action.label}>
                {action.separatorBefore ? <ContextMenu.Separator className="shell-context-separator" /> : null}
                <ContextMenu.Item
                  className={`shell-context-item${action.tone === 'danger' ? ' is-danger' : ''}`}
                  disabled={action.disabled}
                  onSelect={() => {
                    haptic(action.tone === 'danger' ? 'warning' : 'tap')
                    action.onSelect()
                  }}
                >
                  {Icon ? <Icon aria-hidden="true" /> : null}
                  <span>{action.label}</span>
                </ContextMenu.Item>
              </Fragment>
            )
          })}
        </ContextMenu.Content>
      </ContextMenu.Portal>
    </ContextMenu.Root>
  )
}
