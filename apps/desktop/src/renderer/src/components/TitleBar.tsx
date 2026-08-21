/**
 * Custom title bar for the frameless main window. The native Windows title
 * bar is removed (frame:false in main) and replaced by this renderer-painted
 * chrome: brand mark, drag region, and window controls. Pattern adapted from
 * the the predecessor assistant desktop hidden-titlebar shell (docs/UPSTREAM.md).
 *
 * Contract: the whole bar is a drag region (-webkit-app-region: drag); every
 * interactive child opts out with no-drag. Double-click on the drag region
 * toggles maximize, matching Windows shell expectations.
 */
import { useEffect, useState } from 'react'

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
  const [maximized, setMaximized] = useState(false)

  useEffect(() => {
    void window.marvi?.getWindowState().then((state) => setMaximized(state.isMaximized))
    return window.marvi?.onWindowState((state) => setMaximized(state.isMaximized))
  }, [])

  const minimize = (): void => {
    haptic('tap')
    window.marvi?.minimizeWindow()
  }
  const toggleMaximize = (): void => {
    haptic('tap')
    window.marvi?.toggleMaximizeWindow()
  }
  const close = (): void => {
    haptic('close')
    window.marvi?.closeWindow()
  }

  return (
    <header className="titlebar" onDoubleClick={toggleMaximize}>
      {/* The product name and icon were here and said nothing: you know which
          app you opened. The page you are on is the useful half. */}
      <div className="titlebar-brand no-drag">
        <span className="titlebar-page">{page.toUpperCase()}</span>
      </div>
      <div className="titlebar-spacer" />
      <div className="titlebar-controls no-drag" onDoubleClick={(event) => event.stopPropagation()}>
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
        <UiTooltip label="Minimize window" side="bottom">
          <button
            aria-label="Minimize"
            className="titlebar-control"
            onClick={minimize}
            type="button"
          >
            <AbstractIcon name="minimize" size={15} />
          </button>
        </UiTooltip>
        <UiTooltip label={maximized ? 'Restore window' : 'Maximize window'} side="bottom">
          <button
            aria-label={maximized ? 'Restore' : 'Maximize'}
            className="titlebar-control"
            onClick={toggleMaximize}
            type="button"
          >
            <AbstractIcon name={maximized ? 'restore' : 'maximize'} size={15} />
          </button>
        </UiTooltip>
        <UiTooltip label="Close window" side="bottom">
          <button
            aria-label="Close"
            className="titlebar-control close"
            onClick={close}
            type="button"
          >
            <AbstractIcon name="close" size={15} />
          </button>
        </UiTooltip>
      </div>
    </header>
  )
}
