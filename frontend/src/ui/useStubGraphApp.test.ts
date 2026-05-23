import { describe, expect, it } from 'vitest'

import { getMutationTaskSeed, getRunGraphStaleState, pickCreatedSnapshotProject } from './useStubGraphApp'

describe('useStubGraphApp mutation task helpers', () => {
  it('builds task seed from direct task fields', () => {
    const seed = getMutationTaskSeed({
      path: 'repo/README.md',
      saved: true,
      task_id: 'mutation-1',
      task_status: 'running',
      index_status: 'rescan_scheduled',
    })

    expect(seed).toEqual({ task_id: 'mutation-1', status: 'running' })
  })

  it('falls back to rescan_task and defaults to pending', () => {
    const seed = getMutationTaskSeed({
      path: 'repo/README.md',
      saved: true,
      index_status: 'rescan_scheduled',
      rescan_task: { task_id: 'mutation-2', status: 'unknown' },
    })

    expect(seed).toEqual({ task_id: 'mutation-2', status: 'pending' })
  })

  it('returns null when task id is missing', () => {
    const seed = getMutationTaskSeed({
      path: 'repo/README.md',
      saved: true,
      index_status: 'rescan_scheduled',
    })

    expect(seed).toBeNull()
  })
})

describe('useStubGraphApp run warning handling', () => {
  it("marks graph as stale for 'graph not built' warning", () => {
    expect(getRunGraphStaleState('graph not built')).toEqual({
      stale: true,
      message: 'Graph index is not ready. Run Scan/Rescan now to refresh context.',
    })
  })

  it('does not mark graph as stale for other warnings', () => {
    expect(getRunGraphStaleState('other warning')).toEqual({ stale: false, message: null })
  })
})

describe('snapshot project resolution', () => {
  const projects = [
    { id: 1, name: 'alpha', source: { kind: 'root', label: 'Root path' } },
    { id: 2, name: 'beta', source: { kind: 'snapshot', label: 'Snapshot' } },
  ]

  it('prefers project_id from task result', () => {
    const selected = pickCreatedSnapshotProject(projects, { project_id: 2, name: 'other' })
    expect(selected?.id).toBe(2)
  })

  it('falls back to snapshot project name when project_id is missing', () => {
    const selected = pickCreatedSnapshotProject(projects, { name: 'beta' })
    expect(selected?.id).toBe(2)
  })

  it('falls back to first matching name when source marker is missing', () => {
    const selected = pickCreatedSnapshotProject(
      [{ id: 7, name: 'gamma', source: { kind: 'root', label: 'Root path' } }],
      { name: 'gamma' },
    )
    expect(selected?.id).toBe(7)
  })

  it('returns null when no project matches task result', () => {
    const selected = pickCreatedSnapshotProject(projects, { project_id: 999, name: 'missing' })
    expect(selected).toBeNull()
  })
})
