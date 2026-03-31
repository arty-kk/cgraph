import { describe, expect, it } from 'vitest'

import { isTaskStatus } from './taskStatus'

describe('isTaskStatus', () => {
  it('accepts valid task status payload', () => {
    expect(isTaskStatus({ task_id: 'task-1', status: 'pending' })).toBe(true)
  })

  it('rejects malformed payloads', () => {
    expect(isTaskStatus(null)).toBe(false)
    expect(isTaskStatus({ task_id: 1, status: 'pending' })).toBe(false)
    expect(isTaskStatus({ task_id: 'task-1' })).toBe(false)
  })
})
