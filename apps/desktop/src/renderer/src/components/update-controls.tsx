import { useStore } from '@nanostores/react'
import { Popover } from 'radix-ui'
import { useEffect, useState } from 'react'

import {
  $updateView,
  checkForUpdate,
  loadUpdateState,
  setUpdateChannel
} from '../store/update-state'
import { AbstractIcon } from './abstract-icon'
import { UiTooltip } from './ui/tooltip'

function availableText(): string {
  const check = $updateView.get().check
  if (!check) return 'Not checked'
  if (check.error) return check.error
  if (check.upToDate) return 'Up to date'
  return check.channel === 'dev'
    ? `${check.behindBy} commits available`
    : `${check.targetRef ?? 'New release'} available`
}

function UpdateButtons(): React.JSX.Element {
  const view = useStore($updateView)
  const [confirming, setConfirming] = useState(false)
  const available = Boolean(view.check && !view.check.upToDate && !view.check.error)

  if (confirming) {
    return (
      <div className="update-actions">
        <button
          className="ui-button primary"
          onClick={() => void window.marvi?.startUpdate()}
          type="button"
        >
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
      <button
        className="ui-button"
        disabled={view.loading}
        onClick={() => void checkForUpdate()}
        type="button"
      >
        {view.loading ? 'CHECKING…' : 'CHECK UPDATE'}
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
        void loadUpdateState()
        void window.marvi
          ?.getBuildInfo()
          .then((info) => setBuild({ commit: info.commit, buildTime: info.buildTime }))
      }}
    >
      <UiTooltip label="Version and update details" side="top">
        <Popover.Trigger asChild>
          <button
            aria-label={`Version ${version}. Open update details`}
            className="status-item status-version"
            type="button"
          >
            v{version}
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
          <dl className="version-popover-facts">
            <div>
              <dt>STATUS</dt>
              <dd>{availableText()}</dd>
            </div>
            <div>
              <dt>UPDATER</dt>
              <dd>{view.status?.supported ? 'Ready' : 'Unavailable in this build'}</dd>
            </div>
            {build ? (
              <>
                <div>
                  <dt>COMMIT</dt>
                  <dd>{build.commit.slice(0, 10)}</dd>
                </div>
                <div>
                  <dt>BUILT</dt>
                  <dd>{build.buildTime}</dd>
                </div>
              </>
            ) : null}
            {view.result ? (
              <div>
                <dt>LAST RUN</dt>
                <dd>{view.result.message}</dd>
              </div>
            ) : null}
          </dl>
          <UpdateButtons />
          <button className="version-about-link" onClick={onOpenAbout} type="button">
            VERSION DETAILS →
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

  useEffect(() => {
    void loadUpdateState()
  }, [])

  return (
    <section className="about-updates" aria-label="Updates">
      <header>
        <AbstractIcon name="version" size={20} />
        <div>
          <h3>Updates</h3>
          <p>{availableText()}</p>
        </div>
      </header>
      <div className="about-update-facts">
        <span>
          INSTALLED <strong>{version}</strong>
        </span>
        <span>
          CHANNEL <strong>{channel.toUpperCase()}</strong>
        </span>
        <span>
          SELF-UPDATE <strong>{view.status?.supported ? 'READY' : 'UNAVAILABLE'}</strong>
        </span>
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
      <UpdateButtons />
    </section>
  )
}
