/**
 * What Marvi is thinking, on the page you land on.
 *
 * The Overview answered "are the services up", which is a question about
 * processes, and never "is she going to say anything", which is the question
 * about her. Those come apart constantly and did all week: every service
 * green, the mind turning happily, and nothing reaching anybody because the
 * gate that closes at eleven had closed, or a summary was waiting on a rate
 * limited model, or a feeder had quietly stopped feeding.
 *
 * One strip, three facts, and a way through to the Mind page for the rest.
 */
import { Brain, Cpu, Ear, Gamepad2, Inbox } from 'lucide-react'
import React, { useEffect, useState } from 'react'

import type { InitiativeStatus, ResourceState } from '../../../shared/runtime'

export function OverviewMind({ onOpen }: { onOpen?: () => void }): React.JSX.Element | null {
  const [status, setStatus] = useState<InitiativeStatus | null>(null)
  const [resources, setResources] = useState<ResourceState | null>(null)

  useEffect(() => {
    let disposed = false
    const load = async (): Promise<void> => {
      const next = await window.marvi?.getInitiative()
      if (!disposed && next) setStatus(next)
      const found = await window.marvi?.getResources()
      if (!disposed && found) setResources(found)
    }
    void load()
    const timer = setInterval(() => {
      if (!document.hidden) void load()
    }, 10_000)
    return () => {
      disposed = true
      clearInterval(timer)
    }
  }, [])

  if (!status) return null

  const quiet = status.quiet_because ?? ''
  const waiting = status.waiting ?? []
  const feeders = status.feeders ?? []
  // Wired and producing nothing. The failure that hides, so it is the one
  // worth surfacing on the page nobody has to go looking at.
  const mute = feeders.filter((feeder) => feeder.wired && feeder.events === 0)

  return (
    <section className="ov-mind" aria-label="What Marvi is thinking">
      <button className="ov-mind-head" onClick={onOpen} type="button">
        <Brain aria-hidden="true" />
        <span className={quiet ? 'ov-mind-state is-quiet' : 'ov-mind-state'}>
          {quiet ? 'Quiet' : 'Listening'}
        </span>
        <span className="ov-mind-why">{quiet || 'nothing is holding her back'}</span>
        <span className="ov-mind-open">Mind →</span>
      </button>

      <div className="ov-mind-facts">
        <span className={waiting.length ? 'is-live' : ''}>
          <Inbox aria-hidden="true" />
          {waiting.length ? `${waiting.length} waiting to be said` : 'nothing waiting'}
        </span>

        {resources?.low_resource ? (
          <span className="is-live">
            <Gamepad2 aria-hidden="true" />
            standing down for {resources.because}
          </span>
        ) : (
          <span>
            <Cpu aria-hidden="true" />
            full resources
          </span>
        )}

        <span className={mute.length ? 'is-warn' : ''}>
          <Ear aria-hidden="true" />
          {mute.length
            ? `${mute.map((feeder) => feeder.label.toLowerCase()).join(', ')} silent`
            : `${feeders.filter((feeder) => feeder.wired).length} sources feeding`}
        </span>
      </div>

      {waiting.length > 0 && (
        <p className="ov-mind-waiting">
          {waiting[0].summary} — held because {waiting[0].because || waiting[0].reason}
        </p>
      )}
    </section>
  )
}
