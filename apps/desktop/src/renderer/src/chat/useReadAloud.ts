import { useCallback, useEffect, useRef, useState } from 'react'

import { markdownToSpeechChunks } from './speech-text'

export interface ReadAloudController {
  available: boolean
  readingId: number | null
  announcement: string
  toggle: (id: number, content: string) => void
  stop: () => void
}

export function useReadAloud(scope: string): ReadAloudController {
  const [available, setAvailable] = useState(false)
  const [readingId, setReadingId] = useState<number | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const generation = useRef(0)
  const previousScope = useRef(scope)

  const stop = useCallback(() => {
    generation.current += 1
    window.speechSynthesis?.cancel()
    setReadingId(null)
    setAnnouncement('Read aloud stopped.')
  }, [])

  const toggle = useCallback(
    (id: number, content: string) => {
      if (readingId === id) return stop()
      const synthesis = window.speechSynthesis
      const Utterance = globalThis.SpeechSynthesisUtterance
      const voice = preferredVoice(synthesis)
      if (!synthesis || typeof Utterance !== 'function' || !voice) {
        setAnnouncement('Install or enable a local system voice to use read aloud.')
        return
      }
      const chunks = markdownToSpeechChunks(content)
      if (!chunks.length) {
        setAnnouncement('This response has no readable text.')
        return
      }
      synthesis.cancel()
      const current = generation.current + 1
      generation.current = current
      setReadingId(id)
      setAnnouncement('Reading response aloud.')
      const speak = (index: number): void => {
        if (generation.current !== current) return
        if (index >= chunks.length) {
          setReadingId(null)
          setAnnouncement('Finished reading response.')
          return
        }
        const utterance = new Utterance(chunks[index])
        utterance.voice = voice
        utterance.lang = voice.lang
        utterance.onend = () => speak(index + 1)
        utterance.onerror = () => {
          generation.current += 1
          setReadingId(null)
          setAnnouncement('Read aloud stopped because the system voice failed.')
        }
        synthesis.speak(utterance)
      }
      speak(0)
    },
    [readingId, stop]
  )

  useEffect(() => {
    const synthesis = window.speechSynthesis
    const refresh = (): void => setAvailable(Boolean(preferredVoice(synthesis)))
    refresh()
    synthesis?.addEventListener('voiceschanged', refresh)
    return () => synthesis?.removeEventListener('voiceschanged', refresh)
  }, [])

  useEffect(() => {
    if (previousScope.current === scope) return
    previousScope.current = scope
    stop()
  }, [scope, stop])

  useEffect(() => () => window.speechSynthesis?.cancel(), [])

  return { available, readingId, announcement, toggle, stop }
}

function preferredVoice(synthesis: SpeechSynthesis | undefined): SpeechSynthesisVoice | null {
  if (!synthesis) return null
  const voices = synthesis.getVoices().filter((voice) => voice.localService)
  const language = navigator.language.toLowerCase()
  return (
    voices.find((voice) => voice.default && voice.lang.toLowerCase() === language) ??
    voices.find((voice) => voice.lang.toLowerCase().startsWith(language.split('-')[0])) ??
    voices.find((voice) => voice.default) ??
    voices[0] ??
    null
  )
}
