/**
 * Hermes-style hidden title bar. Electron owns the native Windows window
 * controls; this renderer strip owns only the page title and app action.
 *
 * Contract: the whole bar is a drag region (-webkit-app-region: drag); every
 * interactive child opts out with no-drag. Double-click on the drag region
 * toggles maximize, matching Windows shell expectations.
 */
import { haptic } from '../lib/haptics'
import { AbstractIcon } from './abstract-icon'
import { UiTooltip } from './ui/tooltip'

interface TitleBarProps {
  /** Current nav page, shown in the title text. */
  page: string
  /** Opens Settings. The gear sits with the window controls because that is
   * where a person looks for it, and it keeps configuration out of the
   * sidebar, which is for the things you actually use. */
  onSettings: () => void
}

export function TitleBar({ page, onSettings }: TitleBarProps): React.JSX.Element {
  return (
    <header className="titlebar">
      <div className="titlebar-brand">
        <span className="titlebar-page">{page.toUpperCase()}</span>
      </div>
      <div className="titlebar-spacer" />
      <div className="titlebar-controls no-drag">
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
            <AbstractIcon name="settings" size={15} />
          </button>
        </UiTooltip>
      </div>
    </header>
  )
}
