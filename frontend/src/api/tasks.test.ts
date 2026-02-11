import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RunTaskBody, RunTaskResult, TaskStatus } from './types'

const { post, get } = vi.hoisted(() => ({
  post: vi.fn(),
  get: vi.fn(),
}))

vi.mock('./client', () => ({
  api: { post, get },
}))

import { runTask, waitForTaskResult } from './tasks'

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  post.mockReset()
  get.mockReset()
})

describe('tasks api polling', () => {
  it('does a single POST /run and all next status checks via GET /api/tasks/status/{task_id}', async () => {
    const calls: Array<{ method: 'POST' | 'GET'; url: string }> = []
    const taskId = 'task-42'
    const body: RunTaskBody = {
      target_path: 'src/main.ts',
      prompt: 'test',
      agentic: false,
    }

    const finalResult: RunTaskResult = {
      run_id: 42,
      mode: 'analyze',
      result: { ok: true },
    }

    post.mockImplementationOnce(async (url: string) => {
      calls.push({ method: 'POST', url })
      const status: TaskStatus = { task_id: taskId, status: 'pending' }
      return { data: status }
    })

    const statuses: TaskStatus[] = [
      { task_id: taskId, status: 'running' },
      { task_id: taskId, status: 'succeeded', result: finalResult },
    ]

    get.mockImplementation(async (url: string) => {
      calls.push({ method: 'GET', url })
      const next = statuses.shift()
      if (!next) throw new Error('No status prepared')
      return { data: next }
    })

    const initial = await runTask(7, body, { background: true })
    const result = await waitForTaskResult<RunTaskResult>(initial, { pollIntervalMs: 200, maxAttempts: 5 })

    expect(result).toEqual(finalResult)

    const grouped = calls.reduce<Record<string, number>>((acc, call) => {
      const key = `${call.method} ${call.url}`
      acc[key] = (acc[key] ?? 0) + 1
      return acc
    }, {})

    expect(grouped['POST /api/tasks/7/run']).toBe(1)
    expect(grouped[`GET /api/tasks/status/${taskId}`]).toBeGreaterThanOrEqual(2)
    expect(Object.keys(grouped)).toEqual([
      'POST /api/tasks/7/run',
      `GET /api/tasks/status/${taskId}`,
    ])
  })

  it('times out by elapsed time when maxAttempts is not provided', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2025-01-01T00:00:00Z'))

    const taskId = 'task-timeout'
    const initial: TaskStatus = { task_id: taskId, status: 'pending' }

    get.mockResolvedValue({ data: { task_id: taskId, status: 'running' } satisfies TaskStatus })

    const promise = waitForTaskResult<RunTaskResult>(initial, { pollIntervalMs: 200, timeoutMs: 600 })
    const assertion = expect(promise).rejects.toThrow(/Client-side timeout while waiting for task result/)

    await vi.advanceTimersByTimeAsync(600)

    await assertion
    expect(get).toHaveBeenCalledTimes(3)
  })

  it('uses maxAttempts as explicit backward-compatible override when provided', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2025-01-01T00:00:00Z'))

    const taskId = 'task-max-attempts'
    const initial: TaskStatus = { task_id: taskId, status: 'pending' }

    get.mockResolvedValue({ data: { task_id: taskId, status: 'running' } satisfies TaskStatus })

    const promise = waitForTaskResult<RunTaskResult>(initial, {
      pollIntervalMs: 200,
      timeoutMs: 60_000,
      maxAttempts: 2,
    })
    const assertion = expect(promise).rejects.toThrow(/maxAttempts=2/)

    await vi.advanceTimersByTimeAsync(400)

    await assertion
    expect(get).toHaveBeenCalledTimes(2)
  })


  it('ignores non-finite maxAttempts and still enforces timeoutMs', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2025-01-01T00:00:00Z'))

    const taskId = 'task-nan-max-attempts'
    const initial: TaskStatus = { task_id: taskId, status: 'pending' }

    get.mockResolvedValue({ data: { task_id: taskId, status: 'running' } satisfies TaskStatus })

    const promise = waitForTaskResult<RunTaskResult>(initial, {
      pollIntervalMs: 200,
      timeoutMs: 600,
      maxAttempts: Number.NaN,
    })
    const assertion = expect(promise).rejects.toThrow(/Client-side timeout while waiting for task result/)

    await vi.advanceTimersByTimeAsync(600)

    await assertion
    expect(get).toHaveBeenCalledTimes(3)
  })

  it('allows long-running task to succeed with increased timeoutMs', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2025-01-01T00:00:00Z'))

    const taskId = 'task-long-success'
    const initial: TaskStatus = { task_id: taskId, status: 'pending' }
    const finalResult: RunTaskResult = {
      run_id: 9,
      mode: 'analyze',
      result: { ok: true },
    }

    const statuses: TaskStatus[] = [
      { task_id: taskId, status: 'running' },
      { task_id: taskId, status: 'running' },
      { task_id: taskId, status: 'running' },
      { task_id: taskId, status: 'running' },
      { task_id: taskId, status: 'succeeded', result: finalResult },
    ]

    get.mockImplementation(async () => {
      const next = statuses.shift()
      if (!next) throw new Error('No status prepared')
      return { data: next }
    })

    const promise = waitForTaskResult<RunTaskResult>(initial, {
      pollIntervalMs: 200,
      timeoutMs: 1_500,
    })

    await vi.advanceTimersByTimeAsync(1_000)

    await expect(promise).resolves.toEqual(finalResult)
    expect(get).toHaveBeenCalledTimes(5)
  })

  it('polls mutation indexing task until succeeded', async () => {
    const taskId = 'mutation-42'
    const initial: TaskStatus = { task_id: taskId, status: 'pending' }
    const finalResult = { ok: true, index_status: 'ok', rel_paths: ['repo/README.md'] }

    const statuses: TaskStatus[] = [
      { task_id: taskId, status: 'running' },
      { task_id: taskId, status: 'succeeded', result: finalResult },
    ]

    get.mockImplementation(async (url: string) => {
      expect(url).toBe(`/api/tasks/status/${taskId}`)
      const next = statuses.shift()
      if (!next) throw new Error('No status prepared')
      return { data: next }
    })

    const result = await waitForTaskResult<typeof finalResult>(initial, {
      pollIntervalMs: 100,
      maxAttempts: 5,
    })

    expect(result).toEqual(finalResult)
    expect(get).toHaveBeenCalledTimes(2)
  })

})
