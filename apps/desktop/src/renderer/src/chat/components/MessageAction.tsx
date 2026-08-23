import { useState } from 'react'

import { AbstractIcon } from '../../components/abstract-icon'
import { TooltipProvider, UiTooltip } from '../../components/ui/tooltip'

export function CopyMessageAction({
  content,
  label
}: {
  content: string
  label: string
}): React.JSX.Element {
  const [copied, setCopied] = useState(false)

  const copy = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }

  return (
    <TooltipProvider>
      <UiTooltip label={copied ? 'Copied' : label}>
        <button
          aria-label={copied ? 'Copied' : label}
          className="chat-message-action"
          onClick={() => void copy()}
          type="button"
        >
          <AbstractIcon name={copied ? 'check' : 'copy'} size={14} />
        </button>
      </UiTooltip>
    </TooltipProvider>
  )
}
