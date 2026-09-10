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

import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

import './error-boundary.css'

interface State {
  error: Error | null
  stack: string
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null, stack: '' }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Also to the console, which the main process forwards into the app log --
    // so a crash on someone else's machine leaves a trace we can ask for.
    console.error('renderer crashed:', error, info.componentStack)
    this.setState({ stack: info.componentStack ?? '' })
  }

  render(): ReactNode {
    const { error, stack } = this.state
    if (!error) return this.props.children

    return (
      <div className="crash" role="alert">
        <div className="crash-card">
          <h1 className="crash-title">Marvi hit a rendering error</h1>
          <p className="crash-lead">
            The window stopped drawing rather than showing you something wrong. The cause is below.
          </p>
          <pre className="crash-message">{error.message || String(error)}</pre>
          {error.stack ? <pre className="crash-stack">{error.stack}</pre> : null}
          {stack ? <pre className="crash-stack">{stack}</pre> : null}
          <div className="crash-actions">
            <button onClick={() => window.location.reload()} type="button">
              RELOAD
            </button>
            <button
              onClick={() => void navigator.clipboard?.writeText(`${error.stack ?? error.message}\n${stack}`)}
              type="button"
            >
              COPY DETAILS
            </button>
          </div>
        </div>
      </div>
    )
  }
}
