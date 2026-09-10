/**
 * The thing that stands between a render error and a black window.
 *
 * React 19 unmounts the *entire* tree when a render throws and nothing catches
 * it. With no boundary anywhere in this app that meant one bad component took
 * the shell, the sidebar, the background and the title bar with it, and left a
 * black rectangle with no message -- in the window, in the terminal, and in
 * every log. A failure nobody can see is a failure nobody can fix.
 *
 * So this catches, and it shows what broke. Not a friendly apology: the error,
 * the component stack, and a reload button. The audience for this screen is
 * whoever is going to fix it, and they need the stack more than they need
 * reassurance.
 */

import { Component, createRef } from 'react'
import type { ErrorInfo, ReactNode, RefObject } from 'react'

import './error-boundary.css'

type CopyState = 'idle' | 'copying' | 'copied' | 'failed'

interface State {
  error: Error | null
  stack: string
  copied: CopyState
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null, stack: '', copied: 'idle' }

  private detailsRef: RefObject<HTMLDivElement | null> = createRef()

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Also to the console, which the main process forwards into the app log --
    // so a crash on someone else's machine leaves a trace we can ask for.
    console.error('renderer crashed:', error, info.componentStack)
    this.setState({ stack: info.componentStack ?? '' })
  }

  /** Everything somebody would need to paste into a bug report. */
  private details(error: Error): string {
    return [
      error.message || String(error),
      '',
      error.stack ?? '',
      '',
      this.state.stack
    ].join('\n')
  }

  /**
   * Copy, by whichever route works.
   *
   * `navigator.clipboard` is the obvious one and the unreliable one here: it
   * needs a secure context and a focused document, and the crash screen often
   * has neither -- which is why the button silently did nothing. The main
   * process owns a real clipboard, so it goes first and the web API is the
   * fallback. Either way the button says what happened, because a copy button
   * that reports nothing is indistinguishable from a broken one.
   */
  private copy = async (error: Error): Promise<void> => {
    const text = this.details(error)
    this.setState({ copied: 'copying' })
    try {
      if (await window.marvi?.copyText(text)) {
        this.setState({ copied: 'copied' })
        return
      }
    } catch {
      // Fall through to the browser API.
    }
    try {
      await navigator.clipboard.writeText(text)
      this.setState({ copied: 'copied' })
    } catch {
      // Last resort: select it so Ctrl+C works. Nothing else is left.
      this.setState({ copied: 'failed' })
      const node = this.detailsRef.current
      if (node) {
        const range = document.createRange()
        range.selectNodeContents(node)
        const selection = window.getSelection()
        selection?.removeAllRanges()
        selection?.addRange(range)
      }
    }
  }

  render(): ReactNode {
    const { error, stack, copied } = this.state
    if (!error) return this.props.children

    return (
      <div className="crash" role="alert">
        <div className="crash-card">
          <h1 className="crash-title">Marvi hit a rendering error</h1>
          <p className="crash-lead">
            The window stopped drawing rather than showing you something wrong. The cause is below.
          </p>
          <pre className="crash-message">{error.message || String(error)}</pre>
          <div ref={this.detailsRef}>
            {error.stack ? <pre className="crash-stack">{error.stack}</pre> : null}
            {stack ? <pre className="crash-stack">{stack}</pre> : null}
          </div>
          <div className="crash-actions">
            <button onClick={() => window.location.reload()} type="button">
              RELOAD
            </button>
            <button onClick={() => void this.copy(error)} type="button">
              {COPY_LABEL[copied]}
            </button>
          </div>
        </div>
      </div>
    )
  }
}

const COPY_LABEL: Record<CopyState, string> = {
  idle: 'COPY DETAILS',
  copying: 'COPYING…',
  copied: 'COPIED',
  failed: 'SELECTED — PRESS CTRL+C'
}
