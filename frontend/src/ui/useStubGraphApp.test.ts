import { describe, expect, it } from 'vitest'

import { getMutationTaskSeed } from './useStubGraphApp'

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
