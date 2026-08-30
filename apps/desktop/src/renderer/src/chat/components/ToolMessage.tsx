import type { ChatMessage } from '../types'
import { ToolCallsSection } from './ToolCallsSection'

/**
 * A tool result is somebody else's text, so it reads as evidence, not as
 * Marvi. Collapsed by default; expanding reveals the enveloped result.
 */
export function ToolMessage({ message }: { message: ChatMessage }): React.JSX.Element {
  return <ToolCallsSection messages={[message]} />
}
