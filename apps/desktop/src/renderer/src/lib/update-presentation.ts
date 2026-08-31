import type { UpdateCheck } from '../../../shared/runtime'

export interface VersionPresentation {
  label: string
  status: string
  tone: 'idle' | 'available' | 'busy' | 'error'
  tooltip: string
}

interface VersionPresentationInput {
  version: string
  check: UpdateCheck | null
  loading: boolean
  inProgress: boolean
  handoff: 'idle' | 'starting' | 'failed'
}

/** One source of truth for the version button and update surfaces. */
export function resolveVersionPresentation({
  version,
  check,
  loading,
  inProgress,
  handoff
}: VersionPresentationInput): VersionPresentation {
  const base = `v${version}`

  if (handoff === 'starting' || inProgress) {
    return {
      label: `${base} · updating`,
      status: 'Handing off to the updater…',
      tone: 'busy',
      tooltip: 'Marvi will close while the update is applied'
    }
  }
  if (handoff === 'failed') {
    return {
      label: `${base} · update failed`,
      status: 'The updater could not be started',
      tone: 'error',
      tooltip: 'Open update details to retry'
    }
  }
  if (loading && !check) {
    return {
      label: `${base} · checking`,
      status: 'Checking for updates…',
      tone: 'busy',
      tooltip: 'Checking for updates'
    }
  }
  if (check?.error) {
    return {
      label: base,
      status: 'Could not check for updates',
      tone: 'error',
      tooltip: check.error
    }
  }
  if (check?.available) {
    const count = check.behindBy > 0 ? `+${check.behindBy}` : 'update'
    const status =
      check.behindBy > 0
        ? `${check.behindBy} ${check.behindBy === 1 ? 'change' : 'changes'} ready to install`
        : 'An update is ready to install'
    return {
      label: `${base} (${count})`,
      status,
      tone: 'available',
      tooltip: `${status} · ${check.targetRef ?? check.target?.slice(0, 8) ?? 'new build'}`
    }
  }
  if (check?.upToDate) {
    return {
      label: base,
      status: 'Marvi is up to date',
      tone: 'idle',
      tooltip: `${base} is the latest available build`
    }
  }
  return {
    label: base,
    status: 'Update status has not been checked',
    tone: 'idle',
    tooltip: 'Open version and update details'
  }
}
