import type { UpdateCommit } from '../../../shared/runtime'

export interface UpdateChangeGroup {
  id: 'new' | 'fixed' | 'improved' | 'other'
  label: string
  commits: Array<UpdateCommit & { display: string }>
}

const GROUPS: Record<UpdateChangeGroup['id'], string> = {
  new: "What's new",
  fixed: 'Fixed',
  improved: 'Improved',
  other: 'Other changes'
}

const TYPE_GROUP: Record<string, UpdateChangeGroup['id']> = {
  feat: 'new',
  feature: 'new',
  fix: 'fixed',
  hotfix: 'fixed',
  perf: 'improved',
  refactor: 'improved',
  ui: 'improved',
  ux: 'improved'
}

const HEADER = /^([a-zA-Z][\w-]*)(?:\([^)]+\))?!?:\s*(.+)$/

function presentation(summary: string): { group: UpdateChangeGroup['id']; display: string } {
  const line = summary.split(/\r?\n/, 1)[0]?.trim() ?? ''
  const match = HEADER.exec(line)
  const group = match ? (TYPE_GROUP[match[1].toLowerCase()] ?? 'other') : 'other'
  const subject = (match?.[2] ?? line).replace(/[.;,\s]+$/, '').trim()
  return {
    group,
    display: subject ? subject[0].toUpperCase() + subject.slice(1) : 'Update changes'
  }
}

/** Turn raw git subjects into a compact, bounded user-facing changelog while
 * retaining each SHA for provenance and diagnostics. */
export function buildUpdateChangelog(
  commits: readonly UpdateCommit[],
  limit = 8
): UpdateChangeGroup[] {
  const buckets = new Map<UpdateChangeGroup['id'], UpdateChangeGroup['commits']>()
  for (const commit of commits.slice(0, Math.max(0, limit))) {
    const { group, display } = presentation(commit.summary)
    const bucket = buckets.get(group) ?? []
    bucket.push({ ...commit, display })
    buckets.set(group, bucket)
  }
  return (['new', 'fixed', 'improved', 'other'] as const)
    .filter((id) => buckets.has(id))
    .map((id) => ({ id, label: GROUPS[id], commits: buckets.get(id) ?? [] }))
}
