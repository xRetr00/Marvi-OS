import { useState } from 'react'

import { haptic } from '../../lib/haptics'

/**
 * A command to run in a terminal, with a button that copies it.
 *
 * Setup and Doctor used to be pages. Both did their real work by asking the
 * Gateway to inspect the installation — hashing gigabytes of model files,
 * shelling out to check a browser engine — and a page that polls turns a slow
 * answer into a stalled Gateway. It did: opening Setup during a download took
 * Marvi down, because each request cost three and a half seconds and the page
 * asked once a second.
 *
 * The CLI is the better home for both anyway. They are the tools you reach for
 * when the app is not working, and a tool that needs the app to be working is
 * the wrong tool for that job. The GUI's part is to say what to run.
 */
export function CommandCard({
  title,
  command,
  children
}: {
  title: string
  command: string
  children?: React.ReactNode
}): React.JSX.Element {
  const [copied, setCopied] = useState(false)

  const copy = async (): Promise<void> => {
    haptic('tap')
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    } catch {
      // Clipboard can be refused. The command is on screen either way, which
      // is why it is text and not only a button.
    }
  }

  return (
    <div className="command-card">
      <span className="panel-label">{title}</span>
      {children}
      <div className="command-line">
        <code>{command}</code>
        <button className="phase" onClick={() => void copy()} type="button">
          {copied ? 'COPIED' : 'COPY'}
        </button>
      </div>
    </div>
  )
}
