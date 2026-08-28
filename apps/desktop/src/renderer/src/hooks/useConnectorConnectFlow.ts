import { useCallback, useEffect, useRef, useState } from 'react'

import {
  type ConnectPhase,
  POLL_INTERVAL_START_MS,
  POLL_TIMEOUT_MS,
  initialPhaseForStatus,
  nextPollIntervalMs,
  phaseForStatus
} from '../lib/connectors/connectorPolling'
import {
  type ConnectorRequiredField,
  getRequiredFieldsForConnector,
  validateRequiredFieldValues
} from '../lib/connectors/connectorRequiredFields'
import type { ConnectorRow } from '../../../shared/runtime'

export type { ConnectPhase }

interface UseConnectorConnectFlowArgs {
  slug: string
  row?: ConnectorRow
  /** Invoked after a connect or disconnect lands, so the parent can refetch the grid. */
  onChanged?: () => void
}

/**
 * Owns the connect/poll/disconnect state machine for one connector card's
 * modal. Cadence and the focus/visibility poke mirror openhuman's
 * `useComposioConnectFlow` — see `connectorPolling.ts` for why.
 */
export function useConnectorConnectFlow({ slug, row, onChanged }: UseConnectorConnectFlowArgs): {
  phase: ConnectPhase
  error: string | null
  requiredFields: readonly ConnectorRequiredField[]
  fieldValues: Record<string, string>
  setFieldValue: (key: string, value: string) => void
  fieldErrors: Record<string, string>
  connectInFlight: boolean
  handleConnect: () => Promise<void>
  handleDisconnect: (connectionId: string) => Promise<void>
} {
  const pollTimerRef = useRef<number | null>(null)
  const pollDeadlineRef = useRef(0)
  const pollIntervalRef = useRef(POLL_INTERVAL_START_MS)
  const isPollingRef = useRef(false)
  const inFlightRef = useRef(false)
  // Set while polling to fire an immediate re-poll (e.g. on window focus).
  const pokePollRef = useRef<() => void>(() => {})
  const connectInFlightRef = useRef(false)

  const [phase, setPhase] = useState<ConnectPhase>(initialPhaseForStatus(row?.status))
  const [error, setError] = useState<string | null>(null)
  const [connectInFlight, setConnectInFlight] = useState(false)

  const requiredFields = getRequiredFieldsForConnector(slug)
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({})
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const stopPolling = useCallback(() => {
    isPollingRef.current = false
    pokePollRef.current = () => {}
    if (pollTimerRef.current != null) {
      window.clearTimeout(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }, [])

  useEffect(() => () => stopPolling(), [stopPolling])

  const startPolling = useCallback(() => {
    stopPolling()
    isPollingRef.current = true
    pollDeadlineRef.current = Date.now() + POLL_TIMEOUT_MS
    pollIntervalRef.current = POLL_INTERVAL_START_MS

    const scheduleNext = (): void => {
      if (!isPollingRef.current) return
      pollTimerRef.current = window.setTimeout(() => void tick(), pollIntervalRef.current)
      pollIntervalRef.current = nextPollIntervalMs(pollIntervalRef.current)
    }

    const tick = async (): Promise<void> => {
      // Guard against overlapping executions: if a previous tick is still in
      // flight or polling already stopped, skip this round.
      if (inFlightRef.current || !isPollingRef.current) return
      if (Date.now() > pollDeadlineRef.current) {
        stopPolling()
        setPhase('error')
        setError('Timed out waiting for authorization. Try connecting again.')
        return
      }
      inFlightRef.current = true
      try {
        const next = await window.marvi?.getConnectorStatus(slug)
        const mapped = next ? phaseForStatus(next.status) : null
        if (mapped) {
          stopPolling()
          setPhase(mapped)
          setError(next?.error || null)
          onChanged?.()
          return
        }
      } catch {
        // Transient poll failure — retried on the next scheduled tick.
      } finally {
        inFlightRef.current = false
      }
      scheduleNext()
    }

    // Poke an immediate re-poll (used on window focus). Cancels the pending
    // scheduled tick, resets the cadence to fast, and fires now.
    pokePollRef.current = () => {
      if (!isPollingRef.current || inFlightRef.current) return
      if (Date.now() > pollDeadlineRef.current) return
      if (pollTimerRef.current != null) {
        window.clearTimeout(pollTimerRef.current)
        pollTimerRef.current = null
      }
      pollIntervalRef.current = POLL_INTERVAL_START_MS
      void tick()
    }

    void tick()
  }, [onChanged, slug, stopPolling])

  // The user returning from the browser after authorizing is a near-perfect
  // "just finished" signal — poll immediately instead of waiting on the next
  // scheduled tick. No-op unless a poll is currently active.
  useEffect(() => {
    const poke = (): void => pokePollRef.current()
    const onVisibility = (): void => {
      if (document.visibilityState === 'visible') poke()
    }
    window.addEventListener('focus', poke)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.removeEventListener('focus', poke)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

  const validateFields = useCallback((): boolean => {
    if (requiredFields.length === 0) return true
    const errors = validateRequiredFieldValues(requiredFields, fieldValues)
    setFieldErrors(errors)
    return Object.keys(errors).length === 0
  }, [requiredFields, fieldValues])

  const handleConnect = useCallback(async (): Promise<void> => {
    if (connectInFlightRef.current) return
    if (!validateFields()) return

    connectInFlightRef.current = true
    setConnectInFlight(true)
    setPhase('authorizing')
    setError(null)
    setFieldErrors({})

    try {
      // Electron main owns `shell.openExternal`; by the time this resolves
      // the browser tab is already open and polling can start.
      const result = await window.marvi?.connectConnector(slug)
      if (!result?.ok) {
        setPhase('error')
        setError(result?.detail || 'Could not start authorization.')
        return
      }
      setPhase('waiting')
      startPolling()
    } finally {
      connectInFlightRef.current = false
      setConnectInFlight(false)
    }
  }, [slug, startPolling, validateFields])

  const handleDisconnect = useCallback(
    async (connectionId: string): Promise<void> => {
      if (!connectionId) return
      setPhase('disconnecting')
      setError(null)
      try {
        const ok = await window.marvi?.disconnectConnector(connectionId)
        if (ok) {
          setPhase('idle')
          onChanged?.()
        } else {
          setPhase('error')
          setError('Could not disconnect.')
        }
      } catch {
        setPhase('error')
        setError('Could not disconnect.')
      }
    },
    [onChanged]
  )

  return {
    phase,
    error,
    requiredFields,
    fieldValues,
    setFieldValue: (key: string, value: string) =>
      setFieldValues((prev) => ({ ...prev, [key]: value })),
    fieldErrors,
    connectInFlight,
    handleConnect,
    handleDisconnect
  }
}
