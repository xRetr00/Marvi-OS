import { Tr } from '../../store/locale'
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
        {pending.tool.toUpperCase()}{' '}
        <Tr
          text={'needs your approval — this is the same token the Island resolves.'}
          before
          after
        />
      </span>
      <div className="chat-confirm-actions">
        <button className="phase active" type="button" onClick={() => onResolve('approve')}>
          <Tr text={'APPROVE'} />
        </button>
        <button className="phase danger" type="button" onClick={() => onResolve('deny')}>
          <Tr text={'DENY'} />
        </button>
      </div>
    </div>
  )
}
