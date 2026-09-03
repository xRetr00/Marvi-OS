import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ProviderPage, RecogniserPage } from '../../../shared/runtime'

const parakeet = {
  id: 'parakeet-tdt',
  name: 'Parakeet TDT',
  description: 'Default recogniser',
  runtime: 'in-process',
  available: true,
  measured: {}
}
const kyutai = {
  id: 'kyutai-1b',
  name: 'Kyutai STT 1B',
  description: 'Streaming recogniser',
  runtime: 'in-process',
  available: true,
  measured: {}
}
const unavailable = { ...kyutai, id: 'missing', available: false }
const page: RecogniserPage = {
  setting: 'MARVI_STT_ENGINE',
  selected: 'parakeet-tdt',
  missing: false,
  engines: [parakeet, kyutai, unavailable]
}

describe('recogniser selection', () => {
  const getRecognisers = vi.fn(async () => page)
  const setProviderSettings = vi.fn(
    async (_values: Record<string, string>): Promise<ProviderPage | null> => ({}) as ProviderPage
  )

  beforeEach(() => {
    vi.resetModules()
    getRecognisers.mockClear()
    setProviderSettings.mockClear()
    vi.stubGlobal('window', { marvi: { getRecognisers, setProviderSettings } })
  })

  afterEach(() => vi.unstubAllGlobals())

  it('loads the saved Gateway selection', async () => {
    const { $recognisers, refreshRecognisers } = await import('./recognisers')

    await refreshRecognisers()

    expect($recognisers.get()?.selected).toBe('parakeet-tdt')
  })

  it('writes the catalog setting and reconciles both picker surfaces', async () => {
    const { $recognisers, chooseRecogniser } = await import('./recognisers')
    $recognisers.set(page)
    getRecognisers.mockResolvedValueOnce({ ...page, selected: 'kyutai-1b' })

    await expect(chooseRecogniser('kyutai-1b')).resolves.toBe(true)

    expect(setProviderSettings).toHaveBeenCalledWith({ MARVI_STT_ENGINE: 'kyutai-1b' })
    expect($recognisers.get()?.selected).toBe('kyutai-1b')
  })

  it('does not save an unavailable engine', async () => {
    const { $recognisers, chooseRecogniser } = await import('./recognisers')
    $recognisers.set(page)

    await expect(chooseRecogniser('missing')).resolves.toBe(false)
    expect(setProviderSettings).not.toHaveBeenCalled()
  })

  it('rolls back when saving fails', async () => {
    const { $recognisers, chooseRecogniser } = await import('./recognisers')
    $recognisers.set(page)
    setProviderSettings.mockResolvedValueOnce(null)

    await expect(chooseRecogniser('kyutai-1b')).resolves.toBe(false)
    expect($recognisers.get()?.selected).toBe('parakeet-tdt')
  })
})
