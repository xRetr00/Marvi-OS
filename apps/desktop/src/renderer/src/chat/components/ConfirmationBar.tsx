import type { PendingConfirmation } from '../types'

export function ConfirmationBar({
  pending,
  onResolve
}: {
  pending: PendingConfirmation
  onResolve: (decision: 'approve' | 'deny') => void
}): React.JSX.Element {
  return (
    <div className="chat-confirm">
      <span>
        {pending.tool.toUpperCase()} needs your approval — this is the same token the Island
        resolves.
      </span>
      <div className="chat-confirm-actions">
        <button className="phase active" type="button" onClick={() => onResolve('approve')}>
          APPROVE
        </button>
        <button className="phase danger" type="button" onClick={() => onResolve('deny')}>
          DENY
        </button>
      </div>
    </div>
  )
}
