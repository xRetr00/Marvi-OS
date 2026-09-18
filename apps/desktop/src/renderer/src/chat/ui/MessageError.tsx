import { ActionBarPrimitive, MessagePrimitive } from '@assistant-ui/react'
import { AbstractIcon } from '../../components/abstract-icon'

export function describeFailure(raw: string): { title: string; detail: string; technical: string } {
  const technical = raw.trim() || 'An unknown error occurred.'
  const match = technical.match(/\{\s*"error"\s*:\s*\{.*\}/s)
  let detail = technical
  if (match) {
    try {
      const payload = JSON.parse(match[0]) as { error?: { message?: string } }
      detail = payload.error?.message || technical.slice(0, match.index).replace(/[;:\s]+$/, '')
    } catch { /* The provider may send truncated JSON. Keep the original text. */ }
  }
  if (/credits|quota|insufficient balance/i.test(detail))
    return { title: 'Provider credits are exhausted', detail: 'Add credits to the provider account or choose a model with a lower cost, then retry.', technical }
  if (/rate.limit|too many requests|\b429\b/i.test(detail))
    return { title: 'Provider is busy', detail: 'The provider is limiting requests. Try again shortly.', technical }
  if (/unauthorized|invalid.api.key|\b401\b|\b403\b/i.test(detail))
    return { title: 'Provider access failed', detail: 'Check the provider connection and credentials.', technical }
  if (/timeout|timed out/i.test(detail))
    return { title: 'Request timed out', detail: 'The provider did not respond in time. Try again.', technical }
  if (/network|fetch failed|connection|offline/i.test(detail))
    return { title: 'Connection interrupted', detail: 'Check the Gateway and network connection, then retry.', technical }
  return { title: 'Marvi could not finish', detail: detail.length > 280 ? `${detail.slice(0, 277)}…` : detail, technical }
}

export function MessageError({ error }: { error: string }): React.JSX.Element {
  const failure = describeFailure(error)
  return (
    <MessagePrimitive.Error>
      <div className="chat-failure" role="alert">
        <AbstractIcon name="about" size={16} />
        <div className="chat-failure-content">
          <strong>{failure.title}</strong>
          <p>{failure.detail}</p>
          {failure.technical !== failure.detail ? (
            <details><summary>Technical details</summary><pre>{failure.technical}</pre></details>
          ) : null}
        </div>
        <ActionBarPrimitive.Reload className="chat-failure-retry" type="button">
          Retry
        </ActionBarPrimitive.Reload>
      </div>
    </MessagePrimitive.Error>
  )
}
