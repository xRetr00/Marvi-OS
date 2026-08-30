import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, BookOpenText, CalendarDays, RefreshCw, Server } from 'lucide-react'

import type { UsageCounters, UsagePage } from '../../../shared/runtime'
import { ControlButton, ControlPage, ControlSection } from './control-surface'
import { ProcessingCard } from './ui/processing-card'
import { UiTooltip } from './ui/tooltip'
import { ServiceLogo } from '../lib/serviceLogos'
import { buildUsageCells, usageMonthLabels, type UsageRange } from './usage-heatmap'
import { tokenTale } from './token-tale'

function count(value: number): string {
  return new Intl.NumberFormat('en', {
    notation: value >= 100_000 ? 'compact' : 'standard'
  }).format(value)
}

function money(value: number | null | undefined, currency = 'USD'): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return new Intl.NumberFormat('en', { style: 'currency', currency }).format(value)
}

const RANGES: Array<{ id: UsageRange; label: string }> = [
  { id: 'year', label: 'Year' },
  { id: 'month', label: 'Month' },
  { id: 'week', label: 'Week' },
  { id: 'day', label: 'Day' },
  { id: 'hours', label: '24H' }
]

function UsageCalendar({ page }: { page: UsagePage }): React.JSX.Element {
  const [range, setRange] = useState<UsageRange>('year')
  const cells = useMemo(
    () => buildUsageCells(range, page.daily, page.hourly),
    [page.daily, page.hourly, range]
  )
  const calendar = range === 'year' || range === 'month'
  const week = range === 'week'
  const months = calendar ? usageMonthLabels(cells) : []
  const active = cells.filter((cell) => cell.billable > 0)
  const total = cells.reduce((sum, cell) => sum + cell.billable, 0)
  const peak = active.length
    ? active.reduce((best, cell) => (cell.billable > best.billable ? cell : best), active[0])
    : null
  const tale = tokenTale(total)

  return (
    <div className="usage-calendar">
      <div className="usage-range-tabs" role="tablist" aria-label="Usage time range">
        {RANGES.map((item) => (
          <button
            aria-selected={range === item.id}
            className={range === item.id ? 'is-active' : ''}
            key={item.id}
            onClick={() => setRange(item.id)}
            role="tab"
            type="button"
          >
            {item.label}
          </button>
        ))}
      </div>
      <div
        className="usage-heatmap-frame"
        aria-label={`${range} billable token activity`}
        role="group"
      >
        {calendar ? (
          <>
            <div
              className="usage-month-axis"
              style={{ gridTemplateColumns: `repeat(${Math.ceil(cells.length / 7)}, 10px)` }}
            >
              {months.map((month) => (
                <span key={`${month.label}-${month.column}`} style={{ gridColumn: month.column }}>
                  {month.label}
                </span>
              ))}
            </div>
            <div className="usage-heatmap-body">
              <div className="usage-day-axis" aria-hidden="true">
                <span>Mon</span>
                <span>Wed</span>
                <span>Fri</span>
              </div>
              <div className="usage-calendar-grid is-calendar">
                {cells.map((cell) => (
                  <UsageCell cell={cell} key={cell.key} />
                ))}
              </div>
            </div>
          </>
        ) : (
          <>
            <div className="usage-hour-axis" aria-hidden="true">
              <span>00</span>
              <span>06</span>
              <span>12</span>
              <span>18</span>
            </div>
            <div className={`usage-heatmap-body ${week ? 'is-week' : 'is-hours'}`}>
              {week ? (
                <div className="usage-week-axis" aria-hidden="true">
                  {cells
                    .filter((_, index) => index % 24 === 0)
                    .map((cell) => (
                      <span key={cell.key}>{cell.label.slice(0, 6)}</span>
                    ))}
                </div>
              ) : null}
              <div className={`usage-calendar-grid ${week ? 'is-week' : 'is-hours'}`}>
                {cells.map((cell) => (
                  <UsageCell cell={cell} key={cell.key} />
                ))}
              </div>
            </div>
          </>
        )}
      </div>
      <div className="usage-calendar-footer">
        <div>
          <strong>{count(total)}</strong>
          <span>tokens</span>
          <strong>{active.length}</strong>
          <span>active {calendar ? 'days' : 'hours'}</span>
          {peak ? (
            <>
              <strong>{count(peak.billable)}</strong>
              <span>peak</span>
            </>
          ) : null}
        </div>
        <div className="usage-calendar-legend" aria-hidden="true">
          Less{' '}
          {[0, 1, 2, 3, 4].map((level) => (
            <i className={`level-${level}`} key={level} />
          ))}{' '}
          More
        </div>
      </div>
      <div className="usage-token-tale" aria-live="polite">
        <BookOpenText aria-hidden="true" size={16} strokeWidth={1.5} />
        <p>
          <strong>{tale.lead}</strong> <span>{tale.aside}</span>
        </p>
      </div>
    </div>
  )
}

function UsageCell({
  cell
}: {
  cell: ReturnType<typeof buildUsageCells>[number]
}): React.JSX.Element {
  const tooltip = `${cell.label} UTC · ${cell.billable.toLocaleString()} billable tokens`
  return (
    <span
      aria-label={tooltip}
      className={`usage-day level-${cell.level}${cell.inRange ? '' : ' is-outside'}`}
      data-tooltip={tooltip}
      tabIndex={cell.billable > 0 ? 0 : undefined}
    />
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
          <ControlSection
            description="Daily and hourly activity from the local usage ledger. Times are UTC."
            icon={CalendarDays}
            title="Activity"
          >
            <UsageCalendar page={page} />
          </ControlSection>
          <ControlSection
            description="Account totals never replace local counters."
            icon={Server}
            title="Provider sources"
          >
            <div className="usage-provider-list">
              {page.providers
                .filter((provider) => provider.configured || provider.usage.billable > 0)
                .map((provider) => (
                  <article className="usage-provider" key={provider.name}>
                    <div className="usage-provider-identity">
                      <ServiceLogo
                        className="service-brand-logo"
                        height={18}
                        name={provider.name}
                        width={18}
                      />
                      <div>
                        <span>{provider.label}</span>
                        <small>{provider.accountCollection}</small>
                      </div>
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
