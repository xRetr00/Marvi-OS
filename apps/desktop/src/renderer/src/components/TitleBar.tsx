/**
 * Custom title bar for the frameless main window. The native Windows title
 * bar is removed (frame:false in main) and replaced by this renderer-painted
 * chrome: brand mark, drag region, and window controls. Pattern adapted from
 * the Marvi/Hermes desktop hidden-titlebar shell (docs/UPSTREAM.md).
 *
 * Contract: the whole bar is a drag region (-webkit-app-region: drag); every
 * interactive child opts out with no-drag. Double-click on the drag region
 * toggles maximize, matching Windows shell expectations.
 */
import { useEffect, useState } from 'react'

import appIcon from '../assets/app-icon.png'
import { haptic } from '../lib/haptics'

interface TitleBarProps {
  /** Current nav page, shown in the title text. */
  page: string
}

export function TitleBar({ page }: TitleBarProps): React.JSX.Element {
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
      <div className="titlebar-brand no-drag">
        <img alt="Marvi OS" className="titlebar-icon" src={appIcon} />
        <span className="titlebar-product">MARVI OS</span>
        <span className="titlebar-page">{page.toUpperCase()}</span>
      </div>
      <div className="titlebar-spacer" />
      <div className="titlebar-controls no-drag" onDoubleClick={(event) => event.stopPropagation()}>
        <button aria-label="Minimize" className="titlebar-control" onClick={minimize} type="button">
          <span aria-hidden="true">−</span>
        </button>
        <button
          aria-label={maximized ? 'Restore' : 'Maximize'}
          className="titlebar-control"
          onClick={toggleMaximize}
          type="button"
        >
          <span aria-hidden="true">{maximized ? '❐' : '▢'}</span>
        </button>
        <button aria-label="Close" className="titlebar-control close" onClick={close} type="button">
          <span aria-hidden="true">✕</span>
        </button>
      </div>
    </header>
  )
}
