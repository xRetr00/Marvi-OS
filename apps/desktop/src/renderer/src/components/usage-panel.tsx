import { useCallback, useEffect, useMemo, useState } from 'react'

import type { UsageCounters, UsageDay, UsagePage } from '../../../shared/runtime'
import { AbstractIcon } from './abstract-icon'
import { PageLead } from './page-lead'
import { AsciiRule } from './ui/ascii-rule'
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
        LESS{' '}
        {[0, 1, 2, 3, 4].map((level) => (
          <i className={`level-${level}`} key={level} />
        ))}{' '}
        MORE
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
    <section className="single-page panel usage-page">
      <PageLead
        description="Every model token Marvi records, persisted by the Gateway and reconciled with provider account APIs."
        icon="activity"
        title="Usage"
      />
      <div className="usage-toolbar">
        <span>UTC LEDGER / CONTENT-FREE</span>
        <UiTooltip label="Refresh provider account totals">
          <button
            className="phase"
            disabled={refreshing}
            onClick={() => void load(true)}
            type="button"
          >
            <AbstractIcon name="activity" size={14} />{' '}
            {refreshing ? 'REFRESHING' : 'REFRESH ACCOUNTS'}
          </button>
        </UiTooltip>
      </div>
      <AsciiRule />

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
          <div className="usage-metrics">
            <UsageMetric
              label="BILLABLE"
              value={count(totals.billable)}
              note="fresh input + output"
            />
            <UsageMetric label="INPUT" value={count(totals.input)} note="all prompt tokens" />
            <UsageMetric label="OUTPUT" value={count(totals.output)} note="generated tokens" />
            <UsageMetric label="CACHE" value={count(totals.cachedInput)} note="reused input" />
          </div>
          <section className="usage-card">
            <header>
              <span>{'// ACTIVITY / 365 DAYS'}</span>
              <small>Each square is one UTC day</small>
            </header>
            <UsageCalendar days={page.daily} />
          </section>
          <section className="usage-card">
            <header>
              <span>{'// PROVIDER SOURCES'}</span>
              <small>Account totals never replace Marvi counters</small>
            </header>
            <div className="usage-provider-list">
              {page.providers
                .filter((provider) => provider.configured || provider.usage.billable > 0)
                .map((provider) => (
                  <article className="usage-provider" key={provider.name}>
                    <div>
                      <span>{provider.label.toUpperCase()}</span>
                      <small>{provider.accountCollection}</small>
                    </div>
                    <div>
                      <AccountValue page={provider} />
                      <small>{count(provider.usage.billable)} Marvi tokens</small>
                    </div>
                  </article>
                ))}
            </div>
          </section>
        </>
      ) : null}
    </section>
  )
}
