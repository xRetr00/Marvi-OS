import { formatDate, formatDecimal, formatNumber, formatRelative, interpolate, t } from '../store/locale'
import { Tr } from '../store/locale'
/**
 * What Marvi is costing this machine, and what she was doing at the time.
 *
 * Both halves matter and neither is much use alone. "The agent holds 3.2 GB of
 * video memory" is a fact. "The agent holds 3.2 GB of video memory while idle,
 * for the ninth hour running" is the reason a game stutters, and the only
 * difference between the two sentences is the phase label.
 *
 * So the page is built around the split rather than around a total: a band
 * across the top for what she holds now, a table of where it is going, and
 * underneath, the same numbers grouped by what she was doing when they were
 * taken. The last of those is the one that answers "why".
 *
 * ## The timeline reads left to right, oldest first
 *
 * Each column is one reading, coloured by the phase, its height the share of
 * memory she held. A match starting shows up as a step; a model loading shows
 * up as a wall. You are meant to be able to point at the moment.
 */
import { Activity, Cpu, Gauge, HardDrive, MemoryStick, RefreshCw, Zap } from 'lucide-react'
import React, { useEffect, useState } from 'react'

import type {
  ResourceLedger,
  ResourcePhase,
  ResourceProcess,
  ResourceReading
} from '../../../shared/runtime'

/** Megabytes as something a person reads without counting digits. */
function size(mb: number | null | undefined): string {
  if (mb === null || mb === undefined) return '—'
  return mb >= 1024 ? `${formatDecimal(mb / 1024, 1)} GB` : `${formatNumber(Math.round(mb))} MB`
}

function ago(at: number): string {
  const seconds = Math.max(0, Date.now() / 1000 - at)
  if (seconds < 90) return formatRelative(-Math.round(seconds), 'second')
  if (seconds < 5400) return formatRelative(-Math.round(seconds / 60), 'minute')
  return formatRelative(-Math.round(seconds / 3600), 'hour')
}

function moment(at: number): string {
  return formatDate(at * 1000, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

/**
 * What she was doing, in words rather than in field names.
 *
 * `moment` wins over `phase` when both are set, because the lifecycle moments
 * are the expensive ones -- starting, warming, closing, a game beginning -- and
 * a reading taken during one of those is about the moment, not about whether
 * she happened to be listening at the time.
 */
function doingLabel(reading: ResourceReading): string {
  const { busy_with: busy, in_call: inCall, low_resource: low, moment: when, phase } = reading.doing
  if (when === 'game') return busy ? `${busy} started` : 'a game started'
  if (when) return when
  if (low) return busy ? `standing aside for ${busy}` : 'standing aside'
  if (inCall) return phase === 'ready' ? 'in a call' : phase
  return phase === 'ready' ? 'idle' : phase
}

/** One colour per kind of moment, so the timeline is readable at a glance. */
function tone(reading: ResourceReading): string {
  const { in_call: inCall, low_resource: low, moment: when, phase } = reading.doing
  if (when === 'game' || low) return 'game'
  if (when === 'starting' || when === 'warming') return 'warming'
  if (when === 'closing') return 'closing'
  if (phase === 'announcing' || phase === 'speaking') return 'talking'
  if (inCall || phase === 'listening' || phase === 'thinking') return 'call'
  return 'idle'
}

export function ResourcesPage(): React.JSX.Element {
  const [ledger, setLedger] = useState<ResourceLedger | null>(null)
  const [reading, setReading] = useState<ResourceReading | null>(null)
  const [taking, setTaking] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let alive = true
    const read = async (): Promise<void> => {
      const next = await window.marvi?.getResourceHistory(480)
      if (!alive) return
      setLedger(next ?? null)
      setFailed(next === null || next === undefined)
    }
    void read()
    const timer = window.setInterval(() => void read(), 15_000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [])

  const takeOne = async (): Promise<void> => {
    setTaking(true)
    setReading((await window.marvi?.getResourceNow()) ?? null)
    setTaking(false)
    setLedger((await window.marvi?.getResourceHistory(480)) ?? null)
  }

  const readings = ledger?.readings ?? []
  // The fresh reading when there is one, because it is the only one that
  // carries per-process video memory.
  const latest = reading ?? readings[readings.length - 1] ?? null
  const phases = ledger?.summary.by_phase ?? []

  if (failed && !latest) {
    return (
      <section className="res-page">
        <p className="res-empty">
          <Tr
            text={
              'The Gateway is not answering. Nothing has been recorded yet, or it is not running.'
            }
          />
        </p>
      </section>
    )
  }

  return (
    <section className="res-page">
      <header className="res-head">
        <div>
          <h1>
            <Tr text={'Resources'} />
          </h1>
          <p>
            {readings.length > 0
              ? interpolate('{value} readings, oldest {age}', { value: readings.length, age: ago(readings[0].at) })
              : 'Waiting for the first reading.'}
          </p>
        </div>
        <button className="res-take" disabled={taking} onClick={() => void takeOne()} type="button">
          <RefreshCw aria-hidden="true" className={taking ? 'is-spinning' : ''} />
          {taking ? 'Reading…' : 'Read now'}
        </button>
      </header>

      {latest ? <Holding latest={latest} /> : null}
      {latest ? <Where processes={latest.processes} total={latest.marvi_ram_mb} /> : null}
      {readings.length > 1 ? <Timeline readings={readings} /> : null}
      {phases.length > 0 ? <ByDoing phases={phases} /> : null}
    </section>
  )
}

/** What she holds right now, against what the machine has. */
function Holding({ latest }: { latest: ResourceReading }): React.JSX.Element {
  const ramShare = latest.ram_total_mb > 0 ? latest.marvi_ram_mb / latest.ram_total_mb : 0
  const vramShare =
    latest.vram_total_mb > 0 && latest.marvi_vram_mb !== null
      ? latest.marvi_vram_mb / latest.vram_total_mb
      : 0
  const tight = latest.ram_total_mb > 0 && latest.ram_available_mb / latest.ram_total_mb < 0.12

  return (
    <>
      <div className={`res-now is-${tone(latest)}`}>
        <span className="res-doing">{doingLabel(latest)}</span>
        <span className="res-when">
          {moment(latest.at)} · {ago(latest.at)}
        </span>
      </div>
      <div className="res-bands">
        <Band
          detail={`${size(latest.ram_available_mb)} free of ${size(latest.ram_total_mb)}`}
          icon={<MemoryStick aria-hidden="true" />}
          label={t('Memory she holds')}
          share={ramShare}
          value={size(latest.marvi_ram_mb)}
          warn={tight}
        />
        <Band
          detail={
            latest.marvi_vram_mb === null
              ? 'press Read now for the per-process figure'
              : `${size(latest.vram_used_mb)} used of ${size(latest.vram_total_mb)}`
          }
          icon={<Zap aria-hidden="true" />}
          label={t('Video memory she holds')}
          share={vramShare}
          value={size(latest.marvi_vram_mb)}
        />
        <Band
          detail={`the machine as a whole is at ${Math.round(latest.cpu_percent)}%`}
          icon={<Cpu aria-hidden="true" />}
          label={t('Processor')}
          share={latest.processes.reduce((sum, one) => sum + one.cpu_percent, 0) / 100 / 8}
          value={`${Math.round(latest.processes.reduce((sum, one) => sum + one.cpu_percent, 0))}%`}
        />
        <Band
          detail={interpolate('{value} GB free', { value: Math.round(latest.disk_free_gb) })}
          icon={<HardDrive aria-hidden="true" />}
          label={t('Read from disk')}
          share={0}
          value={size(latest.processes.reduce((sum, one) => sum + one.read_mb, 0))}
        />
      </div>
    </>
  )
}

function Band({
  detail,
  icon,
  label,
  share,
  value,
  warn = false
}: {
  detail: string
  icon: React.ReactNode
  label: string
  share: number
  value: string
  warn?: boolean
}): React.JSX.Element {
  return (
    <article className={`res-band${warn ? ' is-warn' : ''}`}>
      <header>
        {icon}
        <span>{label}</span>
      </header>
      <strong>{value}</strong>
      <div className="res-meter">
        <span style={{ width: `${Math.min(100, Math.max(0, share * 100))}%` }} />
      </div>
      <p>{detail}</p>
    </article>
  )
}

/** Where it is going, process by process. */
function Where({
  processes,
  total
}: {
  processes: ResourceProcess[]
  total: number
}): React.JSX.Element {
  return (
    <section className="res-block">
      <h2>
        <Tr text={'Where it is going'} />
      </h2>
      <div className="res-scroll">
        <table className="res-table">
          <thead>
            <tr>
              <th>
                <Tr text={'Process'} />
              </th>
              <th>
                <Tr text={'Memory'} />
              </th>
              <th>
                <Tr text={'Video'} />
              </th>
              <th>
                <Tr text={'CPU'} />
              </th>
              <th>
                <Tr text={'Read'} />
              </th>
              <th>
                <Tr text={'Up'} />
              </th>
            </tr>
          </thead>
          <tbody>
            {processes.map((one) => (
              <tr key={one.pid}>
                <td>
                  <span className="res-role">{one.role}</span>
                  <span className="res-pid">
                    <Tr text={'pid'} after />
                    {one.pid}
                  </span>
                </td>
                <td>
                  {size(one.rss_mb)}
                  <span className="res-share">
                    {total > 0 ? `${Math.round((one.rss_mb / total) * 100)}%` : ''}
                  </span>
                </td>
                <td className={one.vram_mb ? 'is-heavy' : ''}>{size(one.vram_mb)}</td>
                <td>{one.cpu_percent.toFixed(1)}%</td>
                <td>{size(one.read_mb)}</td>
                <td>
                  {one.alive_seconds >= 3600
                    ? `${(one.alive_seconds / 3600).toFixed(1)}h`
                    : `${Math.round(one.alive_seconds / 60)}m`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

/** One column per reading, coloured by what she was doing. */
function Timeline({ readings }: { readings: ResourceReading[] }): React.JSX.Element {
  const shown = readings.slice(-160)
  const peak = Math.max(...shown.map((one) => one.marvi_ram_mb), 1)

  return (
    <section className="res-block">
      <h2>
        <Tr text={'Over time'} />
      </h2>
      <div className="res-timeline">
        {shown.map((one) => (
          <span
            className={`res-tick is-${tone(one)}`}
            key={one.at}
            style={{ height: `${Math.max(3, (one.marvi_ram_mb / peak) * 100)}%` }}
            title={`${moment(one.at)} — ${doingLabel(one)} — ${size(one.marvi_ram_mb)}`}
          />
        ))}
      </div>
      <ul className="res-key">
        {(
          [
            ['idle', 'idle'],
            ['call', 'in a call'],
            ['talking', 'talking'],
            ['warming', 'starting or warming'],
            ['game', 'standing aside'],
            ['closing', 'closing']
          ] as const
        ).map(([name, label]) => (
          <li key={name}>
            <i className={`is-${name}`} />
            {label}
          </li>
        ))}
      </ul>
    </section>
  )
}

/**
 * The same numbers, grouped by what she was doing.
 *
 * This is the table that answers "why". An average over a day says she uses
 * three gigabytes; this says she uses three gigabytes *while idle*, which is a
 * different sentence and the one that gets something fixed.
 */
function ByDoing({ phases }: { phases: ResourcePhase[] }): React.JSX.Element {
  return (
    <section className="res-block">
      <h2>
        <Tr text={'By what she was doing'} />
      </h2>
      <div className="res-scroll">
        <table className="res-table">
          <thead>
            <tr>
              <th>
                <Tr text={'Doing'} />
              </th>
              <th>
                <Tr text={'Readings'} />
              </th>
              <th>
                <Tr text={'Memory'} />
              </th>
              <th>
                <Tr text={'Worst'} />
              </th>
              <th>
                <Tr text={'Video'} />
              </th>
              <th>
                <Tr text={'CPU'} />
              </th>
            </tr>
          </thead>
          <tbody>
            {phases.map((one) => (
              <tr key={one.doing}>
                <td>
                  <span className="res-role">{one.doing || 'idle'}</span>
                </td>
                <td>{one.readings}</td>
                <td>{size(one.ram_mb)}</td>
                <td>{size(one.worst_ram_mb)}</td>
                <td className={one.vram_mb ? 'is-heavy' : ''}>{size(one.vram_mb)}</td>
                <td>{one.cpu_percent.toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="res-note">
        <Activity aria-hidden="true" />
        <Tr
          text={
            'Readings are taken every thirty seconds, and immediately whenever what she is doing changes — a call starting, a model loading, a game taking the machine. Those are the ones worth reading.'
          }
          after
        />
      </p>
      <p className="res-note">
        <Gauge aria-hidden="true" />
        <Tr
          text={
            'Video memory is only measured when a reading goes looking for it, which costs a Windows performance counter. Press'
          }
          after
        />
        <strong>
          <Tr text={'Read now'} />
        </strong>{' '}
        <Tr
          text={
            'for a current figure; a dash means that reading did not ask, never that the answer was zero.'
          }
          before
          after
        />
      </p>
    </section>
  )
}
