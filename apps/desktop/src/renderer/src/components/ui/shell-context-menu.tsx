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
import type { ReactNode } from 'react'

import { haptic } from '../../lib/haptics'

export interface ShellMenuAction {
  label: string
  onSelect: () => void
  disabled?: boolean
}

interface ShellContextMenuProps {
  children: ReactNode
  actions: ShellMenuAction[]
}

export function ShellContextMenu({ actions, children }: ShellContextMenuProps): React.JSX.Element {
  return (
    <ContextMenu.Root>
      <ContextMenu.Trigger asChild>{children}</ContextMenu.Trigger>
      <ContextMenu.Portal>
        <ContextMenu.Content className="shell-context-menu">
          {actions.map((action) => (
            <ContextMenu.Item
              className="shell-context-item"
              disabled={action.disabled}
              key={action.label}
              onSelect={() => {
                haptic('tap')
                action.onSelect()
              }}
            >
              {action.label}
            </ContextMenu.Item>
          ))}
        </ContextMenu.Content>
      </ContextMenu.Portal>
    </ContextMenu.Root>
  )
}
