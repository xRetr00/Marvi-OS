import type { ComponentType, SVGProps } from 'react'

import AionLabs from '@thesvg/react/aionlabs'
import Amazon from '@thesvg/react/amazon'
import Anthropic from '@thesvg/react/anthropic'
import Arcee from '@thesvg/react/arcee'
import Baidu from '@thesvg/react/baidu'
import ByteDance from '@thesvg/react/bytedance'
import Cohere from '@thesvg/react/cohere'
import DeepSeek from '@thesvg/react/deepseek'
import Google from '@thesvg/react/google'
import IBM from '@thesvg/react/ibm'
import InceptionLabs from '@thesvg/react/inception-labs'
import KwaiPilot from '@thesvg/react/kwaipilot'
import Liquid from '@thesvg/react/liquid'
import Meituan from '@thesvg/react/meituan'
import Meta from '@thesvg/react/meta'
import Microsoft from '@thesvg/react/microsoft'
import MiniMax from '@thesvg/react/minimax'
import Mistral from '@thesvg/react/mistral-ai'
import Moonshot from '@thesvg/react/moonshot-ai'
import Morph from '@thesvg/react/morph'
import Nvidia from '@thesvg/react/nvidia'
import OpenAI from '@thesvg/react/openai'
import OpenRouter from '@thesvg/react/openrouter'
import Perplexity from '@thesvg/react/perplexity'
import Qwen from '@thesvg/react/qwen'
import Relace from '@thesvg/react/relace'
import StepFun from '@thesvg/react/stepfun'
import Tencent from '@thesvg/react/tencent'
import Upstage from '@thesvg/react/upstage'
import XAI from '@thesvg/react/x-ai'
import Xiaomi from '@thesvg/react/xiaomi'
import Zhipu from '@thesvg/react/zhipu'

import { modelBrandKey, modelBrandMonogram } from './model-picker-utils'

type BrandComponent = ComponentType<SVGProps<SVGSVGElement> & { variant?: 'mono' }>

const MODEL_BRANDS = Object.freeze({
  aionlabs: AionLabs,
  amazon: Amazon,
  anthropic: Anthropic,
  arcee: Arcee,
  baidu: Baidu,
  bytedance: ByteDance,
  cohere: Cohere,
  deepseek: DeepSeek,
  google: Google,
  ibm: IBM,
  inception: InceptionLabs,
  kwaipilot: KwaiPilot,
  liquid: Liquid,
  meituan: Meituan,
  meta: Meta,
  microsoft: Microsoft,
  minimax: MiniMax,
  mistral: Mistral,
  moonshot: Moonshot,
  morph: Morph,
  nvidia: Nvidia,
  openai: OpenAI,
  openrouter: OpenRouter,
  perplexity: Perplexity,
  qwen: Qwen,
  relace: Relace,
  stepfun: StepFun,
  tencent: Tencent,
  upstage: Upstage,
  xai: XAI,
  xiaomi: Xiaomi,
  zhipu: Zhipu
}) as unknown as Readonly<Record<string, BrandComponent>>

export function ModelBrandLogo({
  className = '',
  label,
  modelId,
  provider
}: {
  className?: string
  label: string
  modelId: string
  provider: string
}): React.JSX.Element {
  const brand = modelBrandKey(modelId, provider)
  const Logo = MODEL_BRANDS[brand]

  return (
    <span aria-hidden="true" className={`model-picker-brand ${className}`} title={brand || label}>
      {Logo ? (
        <Logo focusable="false" variant="mono" />
      ) : (
        <span>{modelBrandMonogram(brand || label)}</span>
      )}
    </span>
  )
}
