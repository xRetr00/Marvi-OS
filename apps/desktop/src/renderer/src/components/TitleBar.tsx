/**
 * Compact hidden title bar. Electron owns the native Windows window
 * controls; this renderer strip owns only the page title and app action.
 *
 * Contract: the whole bar is a drag region (-webkit-app-region: drag); every
 * interactive child opts out with no-drag. Double-click on the drag region
 * toggles maximize, matching Windows shell expectations.
 */
import { useEffect, useState } from 'react'
import { haptic } from '../lib/haptics'
import {
  PanelLeftClose,
  PanelLeftOpen,
  Power,
  RotateCcw,
  Settings,
  Volume2,
  VolumeX,
  type LucideIcon
} from 'lucide-react'
import { UiTooltip } from './ui/tooltip'

interface TitleBarProps {
  /** Current nav page, shown in the title text. */
  page: string
  /** Opens Settings. The gear sits with the window controls because that is
   * where a person looks for it, and it keeps configuration out of the
   * sidebar, which is for the things you actually use. */
  onSettings: () => void
  hapticsMuted: boolean
  onToggleHaptics: () => void
  onRestart: () => void
  onShutdown: () => void
  onToggleSidebar?: () => void
  sidebarCollapsed?: boolean
}

export function TitleBar({
  hapticsMuted,
  onRestart,
  onSettings,
  onShutdown,
  onToggleSidebar,
  onToggleHaptics,
  page,
  sidebarCollapsed = false
}: TitleBarProps): React.JSX.Element {
  return (
    <header className="titlebar" data-shell-context="titlebar">
      <div className="titlebar-brand">
        {onToggleSidebar ? (
          <UiTooltip label={sidebarCollapsed ? 'Show sidebar' : 'Hide sidebar'} side="bottom">
            <button
              aria-label={sidebarCollapsed ? 'Show sidebar' : 'Hide sidebar'}
              aria-pressed={!sidebarCollapsed}
              className="titlebar-control titlebar-sidebar-toggle no-drag"
              onClick={() => {
                haptic('selection')
                onToggleSidebar()
              }}
              type="button"
            >
              {sidebarCollapsed ? <PanelLeftOpen aria-hidden="true" /> : <PanelLeftClose aria-hidden="true" />}
            </button>
          </UiTooltip>
        ) : null}
        <span className="titlebar-page">{page.toUpperCase()}</span>
      </div>
      <div className="titlebar-spacer" />
      <div className="titlebar-controls no-drag">
        <UiTooltip label={hapticsMuted ? 'Unmute haptics' : 'Mute haptics'} side="bottom">
          <button
            aria-label={hapticsMuted ? 'Unmute haptics' : 'Mute haptics'}
            aria-pressed={hapticsMuted}
            className="titlebar-control haptics"
            onClick={onToggleHaptics}
            type="button"
          >
            {hapticsMuted ? <VolumeX aria-hidden="true" /> : <Volume2 aria-hidden="true" />}
          </button>
        </UiTooltip>
        <GuardedLifecycleButton
          icon={RotateCcw}
          label="Restart Marvi and all services"
          onConfirm={onRestart}
          tone="restart"
        />
        <GuardedLifecycleButton
          icon={Power}
          label="Shut down Marvi and all services"
          onConfirm={onShutdown}
          tone="shutdown"
        />
        <UiTooltip label="Open settings" side="bottom">
          <button
            aria-label="Settings"
            className="titlebar-control settings"
            onClick={() => {
              haptic('tap')
              onSettings()
            }}
            type="button"
          >
            <Settings aria-hidden="true" />
          </button>
        </UiTooltip>
      </div>
    </header>
  )
}

function GuardedLifecycleButton({
  icon: Icon,
  label,
  onConfirm,
  tone
}: {
  icon: LucideIcon
  label: string
  onConfirm: () => void
  tone: 'restart' | 'shutdown'
}): React.JSX.Element {
  const [armed, setArmed] = useState(false)

  useEffect(() => {
    if (!armed) return
    const timer = window.setTimeout(() => setArmed(false), 3_000)
    return () => window.clearTimeout(timer)
  }, [armed])

  const tooltip = armed ? `Press again to ${tone}` : label
  return (
    <UiTooltip label={tooltip} side="bottom">
      <button
        aria-label={tooltip}
        aria-pressed={armed}
        className={`titlebar-control lifecycle ${tone}${armed ? ' is-armed' : ''}`}
        onClick={() => {
          if (!armed) {
            haptic('warning')
            setArmed(true)
            return
          }
          onConfirm()
        }}
        type="button"
      >
        <Icon aria-hidden="true" />
      </button>
    </UiTooltip>
  )
}
