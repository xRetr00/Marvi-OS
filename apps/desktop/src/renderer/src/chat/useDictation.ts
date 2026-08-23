import { useCallback, useEffect, useRef, useState } from 'react'

interface Capture {
  id: string
  context: AudioContext
  stream: MediaStream
  source: MediaStreamAudioSourceNode
  processor: ScriptProcessorNode
}

export function useDictation(onText: (text: string) => void): {
  active: boolean
  starting: boolean
  partial: string
  error: string
  start: () => Promise<void>
  stop: () => Promise<void>
} {
  const [active, setActive] = useState(false)
  const [starting, setStarting] = useState(false)
  const [partial, setPartial] = useState('')
  const [error, setError] = useState('')
  const capture = useRef<Capture | null>(null)
  const queue = useRef<Promise<void>>(Promise.resolve())

  const release = useCallback(async (): Promise<Capture | null> => {
    const current = capture.current
    capture.current = null
    if (!current) return null
    current.processor.disconnect()
    current.source.disconnect()
    current.stream.getTracks().forEach((track) => track.stop())
    await current.context.close()
    setActive(false)
    return current
  }, [])

  const start = useCallback(async () => {
    if (active || starting) return
    setStarting(true)
    setPartial('')
    setError('')
    let session
    try {
      session = await window.marvi?.startChatDictation(navigator.language || 'en-US')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Dictation could not start.')
    }
    if (!session) {
      setStarting(false)
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: false,
          autoGainControl: false
        },
        video: false
      })
      const context = new AudioContext()
      await context.resume()
      const source = context.createMediaStreamSource(stream)
      const processor = context.createScriptProcessor(4096, 1, 1)
      source.connect(processor)
      processor.connect(context.destination)
      capture.current = { id: session.id, context, stream, source, processor }
      processor.onaudioprocess = (event) => {
        const pcm = pcm16Base64(event.inputBuffer.getChannelData(0), context.sampleRate)
        queue.current = queue.current
          .then(async () => {
            const response = await window.marvi?.pushChatDictationAudio(session.id, pcm)
            if (response?.text) setPartial(response.text)
          })
          .catch((reason) =>
            setError(reason instanceof Error ? reason.message : 'Dictation stopped.')
          )
      }
      setActive(true)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Microphone access failed.')
      await window.marvi?.cancelChatDictation(session.id)
    } finally {
      setStarting(false)
    }
  }, [active, starting])

  const stop = useCallback(async () => {
    const current = await release()
    if (!current) return
    await queue.current
    const result = await window.marvi?.stopChatDictation(current.id)
    const text = (result?.text || partial).trim()
    if (text) onText(text)
    setPartial('')
  }, [onText, partial, release])

  useEffect(
    () => () => {
      const current = capture.current
      if (current) {
        current.stream.getTracks().forEach((track) => track.stop())
        void window.marvi?.cancelChatDictation(current.id)
      }
    },
    []
  )

  return { active, starting, partial, error, start, stop }
}

function pcm16Base64(samples: Float32Array, sourceRate: number): string {
  const ratio = sourceRate / 16_000
  const length = Math.max(1, Math.floor(samples.length / ratio))
  const bytes = new Uint8Array(length * 2)
  for (let index = 0; index < length; index += 1) {
    const start = Math.floor(index * ratio)
    const end = Math.max(start + 1, Math.floor((index + 1) * ratio))
    let total = 0
    for (let cursor = start; cursor < end && cursor < samples.length; cursor += 1) {
      total += samples[cursor]
    }
    const sample = Math.max(-1, Math.min(1, total / Math.max(1, end - start)))
    const value = sample < 0 ? sample * 0x8000 : sample * 0x7fff
    const integer = Math.round(value)
    bytes[index * 2] = integer & 0xff
    bytes[index * 2 + 1] = (integer >> 8) & 0xff
  }
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000))
  }
  return btoa(binary)
}
