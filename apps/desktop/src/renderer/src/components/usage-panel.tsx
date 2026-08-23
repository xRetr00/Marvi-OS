import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, CalendarDays, RefreshCw, Server } from 'lucide-react'

import type { UsageCounters, UsageDay, UsagePage } from '../../../shared/runtime'
import { ControlButton, ControlPage, ControlSection } from './control-surface'
import { ProcessingCard } from './ui/processing-card'
import { UiTooltip } from './ui/tooltip'

const DAYS = 365

function count(value: number): string {
  return new Intl.NumberFormat('en', {
    notation: value >= 100_000 ? 'compact' : 'standard'
  }).format(value)
}

function money(value: number | null | undefined, currency = 'USD'): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return new Intl.NumberFormat('en', { style: 'currency', currency }).format(value)
}

function UsageCalendar({ days }: { days: UsageDay[] }): React.JSX.Element {
  const cells = useMemo(() => {
    const byDate = new Map(days.map((day) => [day.date, day]))
    const now = new Date()
    const end = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
    const start = end - (DAYS - 1) * 86_400_000
    const result: UsageDay[] = []
    for (let index = 0; index < DAYS; index += 1) {
      const date = new Date(start + index * 86_400_000)
      const key = date.toISOString().slice(0, 10)
      result.push(
        byDate.get(key) ?? {
          date: key,
          input: 0,
          output: 0,
          cachedInput: 0,
          reasoning: 0,
          billable: 0
        }
      )
    }
    return result
  }, [days])
  const peak = Math.max(1, ...cells.map((day) => day.billable))
  return (
    <div className="usage-calendar" aria-label="Daily billable token history for the last year">
      <div className="usage-calendar-grid">
        {cells.map((day) => {
          const level = day.billable === 0 ? 0 : Math.max(1, Math.ceil((day.billable / peak) * 4))
          return (
            <UiTooltip
              key={day.date}
              label={`${day.date}: ${day.billable.toLocaleString()} billable tokens`}
            >
              <span className={`usage-day level-${level}`} />
            </UiTooltip>
          )
        })}
      </div>
      <div className="usage-calendar-legend" aria-hidden="true">
        Less{' '}
        {[0, 1, 2, 3, 4].map((level) => (
          <i className={`level-${level}`} key={level} />
        ))}{' '}
        More
      </div>
    </div>
  )
}

function UsageMetric({
  label,
  value,
  note
}: {
  label: string
  value: string
  note: string
}): React.JSX.Element {
  return (
    <article className="usage-metric">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  )
}

function AccountValue({ page }: { page: UsagePage['providers'][number] }): React.JSX.Element {
  const account = page.account
  if (page.accessPath === 'local') return <strong>LOCAL / NO CHARGE</strong>
  if (!account) return <strong>REQUEST COUNTERS ONLY</strong>
  if (account.state === 'error')
    return <strong className="usage-error">ACCOUNT API UNAVAILABLE</strong>
  if (account.balances?.length) {
    return (
      <strong>
        {account.balances.map((item) => `${item.remaining} ${item.currency}`).join(' / ')}
      </strong>
    )
  }
  if (account.remaining != null)
    return <strong>{money(account.remaining, account.currency)}</strong>
  return <strong>{money(account.periodSpent ?? account.spent, account.currency)}</strong>
}

export function UsagePanel(): React.JSX.Element {
  const [page, setPage] = useState<UsagePage | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async (refresh: boolean): Promise<void> => {
    if (refresh) setRefreshing(true)
    const next = await window.marvi?.getUsage(refresh)
    setPage(next ?? null)
    setError(next ? '' : 'Marvi Gateway did not return usage data.')
    setLoading(false)
    setRefreshing(false)
  }, [])

  useEffect(() => {
    let disposed = false
    void window.marvi?.getUsage(true).then((next) => {
      if (disposed) return
      setPage(next ?? null)
      setError(next ? '' : 'Marvi Gateway did not return usage data.')
      setLoading(false)
    })
    const timer = setInterval(() => void load(false), 15_000)
    return () => {
      disposed = true
      clearInterval(timer)
    }
  }, [load])

  const totals: UsageCounters = page?.totals ?? {
    input: 0,
    output: 0,
    cachedInput: 0,
    reasoning: 0,
    billable: 0
  }

  return (
    <ControlPage
      className="usage-page"
      description="Provider-reported and locally recorded model usage. Message content is never stored here."
      title="Usage"
    >

      {loading ? (
        <ProcessingCard
          detail="Reading the local ledger and the official account endpoints you configured."
          stages={[
            { label: 'Local ledger', state: 'active' },
            { label: 'Provider accounts', state: 'waiting' }
          ]}
          title="Collecting usage"
        />
      ) : error ? (
        <p className="notice notice-warn">{error}</p>
      ) : page ? (
        <>
          <ControlSection
            action={
              <UiTooltip label="Refresh provider account totals">
                <ControlButton disabled={refreshing} onClick={() => void load(true)}>
                  <RefreshCw aria-hidden="true" className={refreshing ? 'is-spinning' : ''} />
                  {refreshing ? 'Refreshing' : 'Refresh'}
                </ControlButton>
              </UiTooltip>
            }
            icon={Activity}
            title="Totals"
          >
          <div className="usage-metrics">
            <UsageMetric
              label="Billable"
              value={count(totals.billable)}
              note="fresh input + output"
            />
            <UsageMetric label="Input" value={count(totals.input)} note="all prompt tokens" />
            <UsageMetric label="Output" value={count(totals.output)} note="generated tokens" />
            <UsageMetric label="Cache" value={count(totals.cachedInput)} note="reused input" />
          </div>
          </ControlSection>
          <ControlSection description="Each square is one UTC day." icon={CalendarDays} title="Activity · 365 days">
            <UsageCalendar days={page.daily} />
          </ControlSection>
          <ControlSection description="Account totals never replace local counters." icon={Server} title="Provider sources">
            <div className="usage-provider-list">
              {page.providers
                .filter((provider) => provider.configured || provider.usage.billable > 0)
                .map((provider) => (
                  <article className="usage-provider" key={provider.name}>
                    <div>
                      <span>{provider.label}</span>
                      <small>{provider.accountCollection}</small>
                    </div>
                    <div>
                      <AccountValue page={provider} />
                      <small>{count(provider.usage.billable)} Marvi tokens</small>
                    </div>
                  </article>
                ))}
            </div>
          </ControlSection>
        </>
      ) : null}
    </ControlPage>
  )
}
