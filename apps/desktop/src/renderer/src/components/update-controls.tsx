import { useStore } from '@nanostores/react'
import { GitCommit, Hash, RefreshCw, ShieldCheck } from 'lucide-react'
import { Popover } from 'radix-ui'
import { useEffect, useState } from 'react'

import type { UpdateCheck } from '../../../shared/runtime'
import { buildUpdateChangelog } from '../lib/update-changelog'
import {
  $updateView,
  checkForUpdate,
  loadUpdateState,
  setUpdateChannel
} from '../store/update-state'
import { AbstractIcon } from './abstract-icon'
import { UiTooltip } from './ui/tooltip'

const shortSha = (sha: string | undefined): string => sha?.slice(0, 8) ?? '—'

function availableText(check: UpdateCheck | null): string {
  if (!check) return 'Checking for updates…'
  if (check.error) return 'Update check failed'
  if (check.upToDate) return 'You have the latest version'
  if (check.behindBy > 0) return `${check.behindBy} ${check.behindBy === 1 ? 'commit' : 'commits'} available`
  return `${check.targetRef ?? 'New version'} available`
}

function checkedText(checkedAt: number | null): string {
  if (!checkedAt) return 'Not checked yet'
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(checkedAt)
}

function CommitChanges({ check, compact = false }: { check: UpdateCheck; compact?: boolean }): React.JSX.Element | null {
  if (!check.available || check.commits.length === 0) return null
  const groups = buildUpdateChangelog(check.commits, compact ? 3 : 8)

  return (
    <div className={compact ? 'update-changes compact' : 'update-changes'}>
      {groups.map((group) => (
        <section key={group.id}>
          <h4>{group.label}</h4>
          <ul>
            {group.commits.map((commit) => (
              <li key={commit.sha}>
                <span>{commit.display}</span>
                <code>{shortSha(commit.sha)}</code>
              </li>
            ))}
          </ul>
        </section>
      ))}
      {check.behindBy > (compact ? 3 : 8) ? (
        <p className="update-more">+{check.behindBy - (compact ? 3 : 8)} more changes</p>
      ) : null}
    </div>
  )
}

function UpdateButtons(): React.JSX.Element {
  const view = useStore($updateView)
  const [confirming, setConfirming] = useState(false)
  const available = Boolean(view.check && !view.check.upToDate && !view.check.error)

  if (confirming) {
    return (
      <div className="update-actions confirm">
        <span>Marvi will close while the bootstrap applies this update.</span>
        <button className="ui-button primary" onClick={() => void window.marvi?.startUpdate()} type="button">
          QUIT + UPDATE
        </button>
        <button className="ui-button" onClick={() => setConfirming(false)} type="button">
          CANCEL
        </button>
      </div>
    )
  }

  return (
    <div className="update-actions">
      <button className="ui-button" disabled={view.loading} onClick={() => void checkForUpdate()} type="button">
        <RefreshCw aria-hidden="true" className={view.loading ? 'spin' : ''} />
        {view.loading ? 'CHECKING…' : 'CHECK AGAIN'}
      </button>
      <button
        className="ui-button primary"
        disabled={!view.status?.supported || !available || view.status?.inProgress}
        onClick={() => setConfirming(true)}
        type="button"
      >
        UPDATE NOW
      </button>
    </div>
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
  const [build, setBuild] = useState<{ commit: string; buildTime: string } | null>(null)

  return (
    <Popover.Root
      onOpenChange={(open) => {
        if (!open) return
        void loadUpdateState().then(() => {
          if (!$updateView.get().check) void checkForUpdate()
        })
        void window.marvi
          ?.getBuildInfo()
          .then((info) => setBuild({ commit: info.commit, buildTime: info.buildTime }))
      }}
    >
      <UiTooltip label="Version and update details" side="top">
        <Popover.Trigger asChild>
          <button aria-label={`Version ${version}. Open update details`} className="status-item status-version" type="button">
            <Hash aria-hidden="true" />
            v{version}
            {view.check?.available ? <span className="update-dot" aria-label="Update available" /> : null}
          </button>
        </Popover.Trigger>
      </UiTooltip>
      <Popover.Portal>
        <Popover.Content align="end" className="version-popover" side="top" sideOffset={7}>
          <header className="version-popover-head">
            <AbstractIcon name="version" size={18} />
            <div>
              <strong>MARVI OS {version}</strong>
              <span>{view.status?.channel?.toUpperCase() ?? 'RELEASE'} CHANNEL</span>
            </div>
          </header>
          <div className={`update-readout${view.check?.error ? ' error' : view.check?.available ? ' available' : ''}`}>
            <span>{view.loading ? 'CHECKING' : 'UPDATE STATUS'}</span>
            <strong>{availableText(view.check)}</strong>
          </div>
          <dl className="version-popover-facts">
            <div><dt>INSTALLED</dt><dd>{shortSha(view.check?.current ?? build?.commit)}</dd></div>
            <div><dt>TARGET</dt><dd>{shortSha(view.check?.target)}</dd></div>
            <div><dt>CHECKED</dt><dd>{checkedText(view.checkedAt)}</dd></div>
          </dl>
          {view.check ? <CommitChanges check={view.check} compact /> : null}
          <UpdateButtons />
          <button className="version-about-link" onClick={onOpenAbout} type="button">
            FULL UPDATE DETAILS →
          </button>
          <Popover.Arrow className="version-popover-arrow" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}

export function AboutUpdates({ version }: { version: string }): React.JSX.Element {
  const view = useStore($updateView)
  const channel = view.status?.channel ?? 'release'
  const check = view.check

  useEffect(() => {
    void loadUpdateState().then(() => {
      if (!$updateView.get().check) void checkForUpdate()
    })
  }, [])

  return (
    <section className="about-updates" aria-label="Updates">
      <div className={`update-readout large${check?.error ? ' error' : check?.available ? ' available' : ''}`}>
        <div>
          <span>{view.loading ? 'CHECKING REMOTE' : 'UPDATE STATUS'}</span>
          <strong>{availableText(check)}</strong>
          <small>Last checked {checkedText(view.checkedAt)}</small>
        </div>
        {check?.signed ? <ShieldCheck aria-label="Signed release" /> : <GitCommit aria-hidden="true" />}
      </div>

      <dl className="about-update-facts">
        <div><dt>INSTALLED</dt><dd>{version}</dd></div>
        <div><dt>CURRENT COMMIT</dt><dd><code>{shortSha(check?.current)}</code></dd></div>
        <div><dt>TARGET</dt><dd><code>{shortSha(check?.target)}</code></dd></div>
        <div><dt>CHANNEL</dt><dd>{channel.toUpperCase()}</dd></div>
        <div><dt>INTEGRITY</dt><dd>{check?.signed === true ? 'SIGNED' : check?.signed === false ? 'UNSIGNED' : 'CHANNEL POLICY'}</dd></div>
        <div><dt>UPDATER</dt><dd>{view.status?.supported ? 'READY' : 'UNAVAILABLE'}</dd></div>
      </dl>

      {check?.error ? <p className="update-error">{check.error}. Check the network connection and try again.</p> : null}
      {check?.available && check.commits.length === 0 ? (
        <p className="update-empty-notes">An update is available, but commit details are unavailable for this checkout.</p>
      ) : null}
      {check ? <CommitChanges check={check} /> : null}

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
      <UpdateButtons />
      {view.result ? (
        <div className={`update-last-run ${view.result.status}`}>
          <span>LAST UPDATE · {view.result.status.toUpperCase()}</span>
          <p>{view.result.message}</p>
        </div>
      ) : null}
    </section>
  )
}
