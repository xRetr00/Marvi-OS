import { describe, expect, it } from 'vitest'

import { buildUpdateChangelog } from './update-changelog'

const commit = (sha: string, summary: string) => ({ sha, summary, author: 'Marvi', at: 1 })

describe('update changelog', () => {
  it('groups conventional commits and keeps their sha', () => {
    const groups = buildUpdateChangelog([
      commit('aaa1111', 'feat(updater): show available commits'),
      commit('bbb2222', 'fix: separate stages from log lines'),
      commit('ccc3333', 'docs: explain the update flow')
    ])

    expect(groups.map((group) => group.label)).toEqual(["What's new", 'Fixed', 'Other changes'])
    expect(groups[0].commits[0]).toMatchObject({ display: 'Show available commits', sha: 'aaa1111' })
  })

  it('bounds the visible changelog', () => {
    const groups = buildUpdateChangelog(
      Array.from({ length: 12 }, (_, index) => commit(String(index), `fix: item ${index}`)),
      3
    )
    expect(groups.flatMap((group) => group.commits)).toHaveLength(3)
  })
})
