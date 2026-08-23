import { useCallback, useEffect, useRef, useState } from 'react'

import { readAloudWithMarvi, stopMarviReadAloud } from '../store/voice-session'
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
      setAnnouncement('Reading response aloud.')
      try {
        await readAloudWithMarvi(chunks.join(' '))
        if (generation.current !== current) return
        setReadingId(null)
        setAnnouncement('Finished reading response.')
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

  return { available, readingId, announcement, toggle, stop }
}
