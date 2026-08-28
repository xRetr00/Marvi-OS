/**
 * Offline brand marks for model and infrastructure services shown outside the
 * connector catalog. TheSVG contains brand identities, not generic UI glyphs,
 * so navigation and actions continue to use the shell's abstract icon set.
 *
 * Keep imports on per-icon subpaths: importing the package barrel would pull
 * thousands of unrelated logos into the renderer bundle.
 */
import type { ComponentType, SVGProps } from 'react'

import Anthropic from '@thesvg/react/anthropic'
import ClaudeCode from '@thesvg/react/claude-code'
import DeepInfra from '@thesvg/react/deepinfra'
import DeepSeek from '@thesvg/react/deepseek'
import LiveKit from '@thesvg/react/livekit'
import LmStudio from '@thesvg/react/lm-studio'
import Ollama from '@thesvg/react/ollama'
import OpenAI from '@thesvg/react/openai'
import OpenCode from '@thesvg/react/opencode'
import OpenRouter from '@thesvg/react/openrouter'
import Vllm from '@thesvg/react/vllm'

export type ServiceLogoComponent = ComponentType<SVGProps<SVGSVGElement>>

export const SERVICE_LOGOS: Readonly<Record<string, ServiceLogoComponent>> = Object.freeze({
  anthropic: Anthropic,
  'claude-code': ClaudeCode,
  codex: OpenAI,
  deepinfra: DeepInfra,
  deepseek: DeepSeek,
  livekit: LiveKit,
  llamacpp: Vllm,
  lmstudio: LmStudio,
  ollama: Ollama,
  openai: OpenAI,
  'openai-responses': OpenAI,
  'opencode-go': OpenCode,
  'opencode-zen': OpenCode,
  openrouter: OpenRouter
})

export function ServiceLogo({
  name,
  ...props
}: { name: string } & SVGProps<SVGSVGElement>): React.JSX.Element | null {
  const Logo = SERVICE_LOGOS[name]
  return Logo ? <Logo aria-hidden="true" focusable="false" {...props} /> : null
}
