import { AssistantRuntimeProvider, useLocalRuntime } from '@assistant-ui/react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { Composer } from './Composer'
import { $runtimeState } from '../../store/voice-state'
import { OFFLINE_RUNTIME } from '../../../../shared/runtime'

/**
 * The composer renders at all, with its slash trigger wired the way the
 * primitives require.
 *
 * This is worth a test only because of how that fails. `Unstable_TriggerPopover`
 * reads a context that `Unstable_TriggerPopoverRoot` provides, and a popover
 * outside its root throws the moment it renders. Nesting is the one mistake
 * this wiring invites and the one nothing else here would catch: the popover is
 * invisible until somebody types a slash, so a broken composer would look
 * exactly like a working one right up to the first `/`.
 */
function Harness(): React.JSX.Element {
  const runtime = useLocalRuntime({
    async run() {
      return { content: [] }
    }
  })
  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <Composer available busy={false} />
    </AssistantRuntimeProvider>
  )
}

describe('the composer', () => {
  const markup = renderToStaticMarkup(<Harness />)

  it('renders with the slash trigger inside its root', () => {
    expect(markup).toContain('chat-compose')
    expect(markup).toContain('Message Marvi')
  })

  it('keeps the command list out of the way until a slash is typed', () => {
    // The popover renders no DOM while the trigger is inactive, so an empty
    // composer is an empty composer.
    expect(markup).not.toContain('chat-slash')
  })

  it('disables the microphone with the low-resource explanation', () => {
    $runtimeState.set({
      ...OFFLINE_RUNTIME,
      resources: { ...OFFLINE_RUNTIME.resources, low_resource: true }
    })
    const disabled = renderToStaticMarkup(<Harness />)
    $runtimeState.set(OFFLINE_RUNTIME)

    expect(disabled).toContain('Voice not working in low-resource mode')
    expect(disabled).toContain('disabled=""')
  })
})
