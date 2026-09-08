/**
 * Compact hidden title bar. Electron owns the native Windows window
 * controls; this renderer strip owns only the page title and app action.
 *
 * Contract: the whole bar is a drag region (-webkit-app-region: drag); every
 * interactive child opts out with no-drag. Double-click on the drag region
 * toggles maximize, matching Windows shell expectations.
 */
import { useEffect, useRef, useState } from 'react'
import { haptic } from '../lib/haptics'
import {
  Gauge,
  Globe,
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
import type { ResourceState } from '../../../shared/runtime'

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
  /** Open or close the browser pane. Absent on pages that have no
   *  conversation to sit beside -- see `App`. */
  onToggleBrowser?: () => void
  browserOpen?: boolean
}

export function TitleBar({
  browserOpen = false,
  hapticsMuted,
  onRestart,
  onSettings,
  onShutdown,
  onToggleBrowser,
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
              {sidebarCollapsed ? (
                <PanelLeftOpen aria-hidden="true" />
              ) : (
                <PanelLeftClose aria-hidden="true" />
              )}
            </button>
          </UiTooltip>
        ) : null}
        <span className="titlebar-page">{page.toUpperCase()}</span>
      </div>
      <div className="titlebar-spacer" />
      <div className="titlebar-controls no-drag">
        {/* Only where there is a conversation for it to sit beside. A browser
            button on the Graph page opens a pane next to a graph, which is
            not the thing anybody meant. */}
        {onToggleBrowser ? (
          <UiTooltip label={browserOpen ? 'Close the browser' : 'Open the browser'} side="bottom">
            <button
              aria-label={browserOpen ? 'Close the browser' : 'Open the browser'}
              aria-pressed={browserOpen}
              className={`titlebar-control browser${browserOpen ? ' is-on' : ''}`}
              onClick={() => {
                haptic('tap')
                onToggleBrowser()
              }}
              type="button"
            >
              <Globe aria-hidden="true" />
            </button>
          </UiTooltip>
        ) : null}
        <LowResourceButton />
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
          setArmed(false)
          haptic('success')
          onConfirm()
        }}
        type="button"
      >
        <Icon aria-hidden="true" />
      </button>
    </UiTooltip>
  )
}

/**
 * Low-resource mode, and a switch for the times it cannot see the reason.
 *
 * Marvi turns this on herself when a fullscreen window appears or the card
 * goes under load, which catches games and misses everything else -- a long
 * export, a compile, a model training in a terminal window. Rather than grow
 * a list of applications she is supposed to recognise, this says it directly.
 *
 * The hand switch adds to the automatic one, it does not override it: while a
 * game is actually detected the mode stays on whatever this says, because a
 * switch that silently stops working is worse than one that explains itself.
 */
function LowResourceButton(): React.JSX.Element {
  const [state, setState] = useState<ResourceState | null>(null)
  const [explaining, setExplaining] = useState(false)
  const [working, setWorking] = useState(false)
  const card = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let alive = true
    const read = async (): Promise<void> => {
      const next = (await window.marvi?.getResources()) ?? null
      if (alive) setState(next)
    }
    void read()
    // Ten seconds: this changes when a game opens, not continuously, and the
    // agent's own poll is thirty. A title bar that repaints every second is
    // something a person notices out of the corner of their eye.
    const timer = window.setInterval(() => void read(), 10_000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    if (!explaining) return
    const away = (event: MouseEvent): void => {
      if (!card.current?.contains(event.target as Node)) setExplaining(false)
    }
    const escape = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setExplaining(false)
    }
    window.addEventListener('mousedown', away)
    window.addEventListener('keydown', escape)
    return () => {
      window.removeEventListener('mousedown', away)
      window.removeEventListener('keydown', escape)
    }
  }, [explaining])

  const on = Boolean(state?.low_resource)
  const automatic = Boolean(state?.automatic)
  const byHand = Boolean(state?.by_hand)

  const toggle = async (): Promise<void> => {
    setWorking(true)
    haptic(byHand ? 'selection' : 'warning')
    const next = await window.marvi?.holdResources(!byHand)
    if (next) setState(next)
    setWorking(false)
  }

  return (
    <div className="titlebar-lowres" ref={card}>
      <UiTooltip
        label={on ? `Standing aside for ${state?.because || 'something'}` : 'Low-resource mode'}
        side="bottom"
      >
        <button
          aria-expanded={explaining}
          aria-label="Low-resource mode"
          aria-pressed={on}
          className={`titlebar-control lowres${on ? ' is-on' : ''}`}
          onClick={() => {
            haptic('tap')
            setExplaining((open) => !open)
          }}
          type="button"
        >
          <Gauge aria-hidden="true" />
        </button>
      </UiTooltip>

      {explaining ? (
        <div className="lowres-card" role="dialog" aria-label="Low-resource mode">
          <header>
            <h3>Low-resource mode</h3>
            <span className={`lowres-pill${on ? ' is-on' : ''}`}>{on ? 'On' : 'Off'}</span>
          </header>
          <p>
            Marvi gets out of the way of whatever else is using this machine. She hands back the
            speech models she is holding on the graphics card, slows the room camera right down, and
            stops thinking out loud unless it matters.
          </p>
          <p className="lowres-note">
            She still talks. Announcements keep working, so you hear anything worth hearing while
            you are busy.
          </p>
          <p className="lowres-why">
            {automatic
              ? `On automatically — ${state?.because} has the machine. It goes off on its own when that closes.`
              : byHand
                ? 'On because you asked. Turn it off when you are done.'
                : 'Off. She turns it on herself for a game; switch it on here for anything she would not recognise — an export, a compile, a model training.'}
          </p>
          <button
            className="lowres-switch"
            disabled={working}
            onClick={() => void toggle()}
            type="button"
          >
            {byHand ? 'Turn it off' : 'Turn it on'}
          </button>
          {automatic && !byHand ? (
            <p className="lowres-foot">A game has it on regardless; this adds to that.</p>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
