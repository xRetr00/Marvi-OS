import { useStore } from '@nanostores/react'
import { Check, Download, GitCommit, Hash, RefreshCw, ShieldCheck, X } from 'lucide-react'
import { Dialog } from 'radix-ui'
import { useEffect, useMemo, useState } from 'react'

import type { UpdateCheck } from '../../../shared/runtime'
import { buildUpdateChangelog } from '../lib/update-changelog'
import { resolveVersionPresentation } from '../lib/update-presentation'
import {
  $updateView,
  beginUpdate,
  checkForUpdate,
  clearUpdateHandoffFailure,
  loadUpdateState,
  setUpdateChannel
} from '../store/update-state'
import { UiTooltip } from './ui/tooltip'

const shortSha = (sha: string | undefined): string => sha?.slice(0, 8) ?? '—'

function relativeCheckTime(checkedAt: number | null): string {
  if (!checkedAt) return 'Never checked'
  const elapsed = Math.max(0, Date.now() - checkedAt)
  if (elapsed < 60_000) return 'Checked just now'
  if (elapsed < 3_600_000) return `Checked ${Math.round(elapsed / 60_000)}m ago`
  if (elapsed < 86_400_000) return `Checked ${Math.round(elapsed / 3_600_000)}h ago`
  return `Checked ${Math.round(elapsed / 86_400_000)}d ago`
}

function CommitChanges({
  check,
  compact = false
}: {
  check: UpdateCheck
  compact?: boolean
}): React.JSX.Element | null {
  if (!check.available || check.commits.length === 0) return null
  const limit = compact ? 4 : 10
  const groups = buildUpdateChangelog(check.commits, limit)
  return (
    <div className={compact ? 'update-changes compact' : 'update-changes'}>
      {groups.map((group) => (
        <section key={group.id}>
          <h4>{group.label}</h4>
          <ul>
            {group.commits.map((commit) => (
              <li key={commit.sha}>
                <span>{commit.display}</span>
                <code title={`${commit.author} · ${new Date(commit.at * 1000).toLocaleString()}`}>
                  {shortSha(commit.sha)}
                </code>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {check.behindBy > limit ? (
        <p className="update-more">+{check.behindBy - limit} more changes</p>
      ) : null}
    </div>
  )
}

function UpdateActions({ compact = false }: { compact?: boolean }): React.JSX.Element {
  const view = useStore($updateView)
  const [confirmingTarget, setConfirmingTarget] = useState<string | null>(null)
  const available = Boolean(view.check?.available && !view.check.error)
  const busy = view.loading || view.handoff === 'starting' || Boolean(view.status?.inProgress)
  const targetKey = view.check?.target ?? view.check?.targetRef ?? 'available'
  const confirming = available && confirmingTarget === targetKey

  if (confirming) {
    return (
      <div className="update-confirmation" role="alert">
        <p>Marvi will close, apply the update in the bootstrap window, then reopen.</p>
        <div className="update-actions">
          <button
            className="ui-button primary"
            disabled={busy}
            onClick={() => void beginUpdate()}
            type="button"
          >
            <Download aria-hidden="true" />
            {view.handoff === 'starting' ? 'STARTING…' : 'QUIT + UPDATE'}
          </button>
          <button
            className="ui-button"
            disabled={busy}
            onClick={() => setConfirmingTarget(null)}
            type="button"
          >
            CANCEL
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className={compact ? 'update-actions compact' : 'update-actions'}>
      <button
        className="ui-button"
        disabled={busy}
        onClick={() => {
          clearUpdateHandoffFailure()
          void checkForUpdate()
        }}
        type="button"
      >
        <RefreshCw aria-hidden="true" className={view.loading ? 'spin' : ''} />
        {view.loading ? 'CHECKING…' : 'CHECK NOW'}
      </button>
      {available ? (
        <button
          className="ui-button primary"
          disabled={!view.status?.supported || busy}
          onClick={() => setConfirmingTarget(targetKey)}
          type="button"
        >
          UPDATE NOW
        </button>
      ) : null}
    </div>
  )
}

function UpdateStatus({
  version,
  compact = false
}: {
  version: string
  compact?: boolean
}): React.JSX.Element {
  const view = useStore($updateView)
  const presentation = useMemo(
    () =>
      resolveVersionPresentation({
        version,
        check: view.check,
        loading: view.loading,
        inProgress: Boolean(view.status?.inProgress),
        handoff: view.handoff
      }),
    [version, view.check, view.loading, view.status?.inProgress, view.handoff]
  )

  return (
    <>
      <div className={`update-state-line ${presentation.tone}`}>
        <span className="update-state-glyph" aria-hidden="true">
          {presentation.tone === 'busy' ? (
            <RefreshCw className="spin" />
          ) : presentation.tone === 'available' ? (
            <Download />
          ) : (
            <Check />
          )}
        </span>
        <div>
          <span>{presentation.tone === 'available' ? 'UPDATE AVAILABLE' : 'UPDATE STATUS'}</span>
          <strong>{presentation.status}</strong>
          <small>{relativeCheckTime(view.checkedAt)}</small>
        </div>
      </div>
      {view.handoff === 'failed' ? (
        <p className="update-error">
          The installed updater could not be started. Marvi stayed open; check again or retry.
        </p>
      ) : view.check?.error ? (
        <p className="update-error">{view.check.error}</p>
      ) : null}
      {view.check?.available && view.check.commits.length === 0 ? (
        <p className="update-empty-notes">
          An update is ready, but detailed change notes are unavailable.
        </p>
      ) : null}
      {view.check ? <CommitChanges check={view.check} compact={compact} /> : null}
    </>
  )
}

export function VersionPopover({
  version,
  onOpenAbout
}: {
  version: string
  onOpenAbout: () => void
}): React.JSX.Element {
  const view = useStore($updateView)
  const [open, setOpen] = useState(false)
  const presentation = resolveVersionPresentation({
    version,
    check: view.check,
    loading: view.loading,
    inProgress: Boolean(view.status?.inProgress),
    handoff: view.handoff
  })

  const onOpenChange = (next: boolean): void => {
    setOpen(next)
    if (!next) return
    void loadUpdateState().then(() => {
      const current = $updateView.get()
      if (!current.check || !current.checkedAt || Date.now() - current.checkedAt > 5 * 60 * 1000)
        void checkForUpdate()
    })
  }

  return (
    <Dialog.Root onOpenChange={onOpenChange} open={open}>
      <UiTooltip label={presentation.tooltip} side="top">
        <Dialog.Trigger asChild>
          <button
            aria-label={`${presentation.label}. ${presentation.status}`}
            className={`status-item status-version update-${presentation.tone}`}
            type="button"
          >
            {presentation.tone === 'busy' ? (
              <RefreshCw aria-hidden="true" className="spin" />
            ) : (
              <Hash aria-hidden="true" />
            )}
            <span>{presentation.label}</span>
          </button>
        </Dialog.Trigger>
      </UiTooltip>
      <Dialog.Portal>
        <Dialog.Overlay className="update-overlay-scrim" />
        <Dialog.Content aria-describedby="update-center-description" className="update-center">
          <header className="update-center-head">
            <div>
              <span>MARVI DESKTOP</span>
              <Dialog.Title>Version {version}</Dialog.Title>
              <Dialog.Description id="update-center-description">
                Installed build and available changes
              </Dialog.Description>
            </div>
            <Dialog.Close aria-label="Close update details" className="update-center-close">
              <X aria-hidden="true" />
            </Dialog.Close>
          </header>
          <UpdateStatus compact version={version} />
          <dl className="update-build-line">
            <div>
              <dt>INSTALLED</dt>
              <dd>{shortSha(view.check?.current)}</dd>
            </div>
            <div>
              <dt>TARGET</dt>
              <dd>{shortSha(view.check?.target)}</dd>
            </div>
            <div>
              <dt>CHANNEL</dt>
              <dd>{view.status?.channel?.toUpperCase() ?? 'RELEASE'}</dd>
            </div>
          </dl>
          <UpdateActions compact />
          <button
            className="version-about-link"
            onClick={() => {
              setOpen(false)
              onOpenAbout()
            }}
            type="button"
          >
            OPEN ABOUT + UPDATE SETTINGS →
          </button>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

export function AboutUpdates({ version }: { version: string }): React.JSX.Element {
  const view = useStore($updateView)
  const channel = view.status?.channel ?? 'release'

  useEffect(() => {
    void loadUpdateState().then(() => {
      if (!$updateView.get().check) void checkForUpdate()
    })
  }, [])

  return (
    <section className="about-updates" aria-label="Updates">
      <UpdateStatus version={version} />
      <dl className="about-update-facts">
        <div>
          <dt>VERSION</dt>
          <dd>{version}</dd>
        </div>
        <div>
          <dt>RUNNING</dt>
          <dd>
            <code>{shortSha(view.check?.current)}</code>
          </dd>
        </div>
        <div>
          <dt>TARGET</dt>
          <dd>
            <code>{shortSha(view.check?.target)}</code>
          </dd>
        </div>
        <div>
          <dt>CHANNEL</dt>
          <dd>{channel.toUpperCase()}</dd>
        </div>
        <div>
          <dt>INTEGRITY</dt>
          <dd>
            {view.check?.signed === true ? (
              <>
                <ShieldCheck aria-hidden="true" /> SIGNED
              </>
            ) : (
              'CHANNEL POLICY'
            )}
          </dd>
        </div>
        <div>
          <dt>UPDATER</dt>
          <dd>{view.status?.supported ? 'READY' : 'UNAVAILABLE'}</dd>
        </div>
      </dl>
      <div className="update-settings-row">
        <div>
          <strong>Automatic checks</strong>
          <span>At startup, every 30 minutes, and after returning to Marvi.</span>
        </div>
        <div className="update-channel" aria-label="Update channel">
          {(['release', 'dev'] as const).map((item) => (
            <button
              aria-pressed={channel === item}
              className={channel === item ? 'ui-button active' : 'ui-button'}
              key={item}
              onClick={() => void setUpdateChannel(item)}
              type="button"
            >
              {item.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
      <UpdateActions />
      {view.result ? (
        <div className={`update-last-run ${view.result.status}`}>
          <span>LAST UPDATE · {view.result.status.toUpperCase()}</span>
          <p>{view.result.message}</p>
        </div>
      ) : null}
      <div className="update-provenance">
        <GitCommit aria-hidden="true" />
        <span>Change details come from the commits between the running and target builds.</span>
      </div>
    </section>
  )
}
