import { describe, expect, it } from 'vitest'

import { getMutationTaskSeed, getRunGraphStaleState } from './useStubGraphApp'

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
