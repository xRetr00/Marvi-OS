import { useCallback, useEffect, useRef, useState } from 'react'

import { readAloudWithMarvi, stopMarviReadAloud } from '../store/announcer'
import { markdownToSpeechChunks } from './speech-text'

export interface ReadAloudController {
  available: boolean
  readingId: number | null
  announcement: string
  toggle: (id: number, content: string) => void
  stop: () => void
}

export function useReadAloud(scope: string): ReadAloudController {
  const [available] = useState(true)
  const [readingId, setReadingId] = useState<number | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const generation = useRef(0)
  const previousScope = useRef(scope)

  const stop = useCallback(() => {
    generation.current += 1
    void stopMarviReadAloud()
    setReadingId(null)
    setAnnouncement('Read aloud stopped.')
  }, [])

  const toggle = useCallback(
    async (id: number, content: string) => {
      if (readingId === id) return stop()
      const chunks = markdownToSpeechChunks(content)
      if (!chunks.length) {
        setAnnouncement('This response has no readable text.')
        return
      }
      const current = generation.current + 1
      generation.current = current
      setReadingId(id)
      setAnnouncement('Preparing speech…')
      try {
        const result = await readAloudWithMarvi(chunks.join(' '))
        if (generation.current !== current) return
        setReadingId(null)
        setAnnouncement(result.cancelled ? 'Read aloud stopped.' : 'Finished reading response.')
      } catch (cause) {
        if (generation.current !== current) return
        generation.current += 1
        setReadingId(null)
        setAnnouncement(
          cause instanceof Error ? cause.message : 'Marvi could not read this response.'
        )
      }
    },
    [readingId, stop]
  )

  useEffect(() => {
    if (previousScope.current === scope) return
    previousScope.current = scope
    stop()
  }, [scope, stop])

  useEffect(() => () => void stopMarviReadAloud(), [])

  useEffect(() => {
    if (readingId !== null || !announcement) return
    const timer = window.setTimeout(() => setAnnouncement(''), 4_000)
    return () => window.clearTimeout(timer)
  }, [announcement, readingId])

  return { available, readingId, announcement, toggle, stop }
}
