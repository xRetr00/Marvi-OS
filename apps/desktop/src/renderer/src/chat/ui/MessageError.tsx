import { Tr, t } from '../../store/locale'
import { ActionBarPrimitive, MessagePrimitive } from '@assistant-ui/react'
import { AbstractIcon } from '../../components/abstract-icon'
import { describeFailure } from './describeFailure'

export function MessageError({ error }: { error: string }): React.JSX.Element {
  const failure = describeFailure(error)
  return (
    <MessagePrimitive.Error>
      <div className="chat-failure" role="alert">
        <AbstractIcon name="about" size={16} />
        <div className="chat-failure-content">
          <strong>{t(failure.title)}</strong>
          <p dir="auto">{t(failure.detail)}</p>
          {failure.technical !== failure.detail ? (
            <details>
              <summary>
                <Tr text={'Technical details'} />
              </summary>
              <pre dir="ltr">{failure.technical}</pre>
            </details>
          ) : null}
        </div>
        <ActionBarPrimitive.Reload className="chat-failure-retry" type="button">
          <Tr text={'Retry'} />
        </ActionBarPrimitive.Reload>
      </div>
    </MessagePrimitive.Error>
  )
}
