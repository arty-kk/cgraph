import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RunTaskBody, RunTaskResult, TaskStatus } from '@/shared/types'

const { post, get } = vi.hoisted(() => ({
  post: vi.fn(),
  get: vi.fn(),
}))

vi.mock('@/shared/api/client', () => ({
  api: { post, get },
}))

import { runTask, waitForTaskResult } from './api'
import { TaskFailureError } from './taskStatus'

function assertRunTaskContract(): void {
  const body = {
    target_path: 'src/main.ts',
    prompt: 'contract',
    agentic: false,
  } satisfies RunTaskBody

  void runTask(1, body)
  // @ts-expect-error polling options belong to waitForTaskResult, runTask accepts only 2 args
  void runTask(1, body, { pollIntervalMs: 200 })
}
void assertRunTaskContract

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  post.mockReset()
  get.mockReset()
})

describe('tasks api polling', () => {

  it('keeps polling options in waitForTaskResult and does not pass them through runTask', async () => {
    const taskId = 'task-contract'
    const body: RunTaskBody = {
      target_path: 'src/main.ts',
      prompt: 'contract',
      agentic: false,
    }
    const finalResult: RunTaskResult = {
      run_id: 101,
      mode: 'analyze',
      result: { ok: true },
    }

    post.mockResolvedValueOnce({ data: { task_id: taskId, status: 'pending' } satisfies TaskStatus })

    get
      .mockResolvedValueOnce({ data: { task_id: taskId, status: 'running' } satisfies TaskStatus })
      .mockResolvedValueOnce({
        data: { task_id: taskId, status: 'succeeded', result: finalResult } satisfies TaskStatus,
      })

    const initial = await runTask(7, body)
    const result = await waitForTaskResult<RunTaskResult>(initial, {
      pollIntervalMs: 200,
      maxAttempts: 5,
    })

    expect(result).toEqual(finalResult)
    expect(post).toHaveBeenCalledTimes(1)
    expect(post).toHaveBeenCalledWith('/tasks/7/run', body)
    expect(post.mock.calls[0]).toHaveLength(2)
    expect(get).toHaveBeenCalledTimes(2)
  })
  it('does a single POST /run and all next status checks via GET /tasks/status/{task_id}', async () => {
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

    const initial = await runTask(7, body)
    const result = await waitForTaskResult<RunTaskResult>(initial, { pollIntervalMs: 200, maxAttempts: 5 })

    expect(result).toEqual(finalResult)

    const grouped = calls.reduce<Record<string, number>>((acc, call) => {
      const key = `${call.method} ${call.url}`
      acc[key] = (acc[key] ?? 0) + 1
      return acc
    }, {})

    expect(grouped['POST /tasks/7/run']).toBe(1)
    expect(grouped[`GET /tasks/status/${taskId}`]).toBeGreaterThanOrEqual(2)
    expect(Object.keys(grouped)).toEqual([
      'POST /tasks/7/run',
      `GET /tasks/status/${taskId}`,
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

  it('uses structured task error payload fields when task fails', async () => {
    const taskId = 'task-failed'
    const initial: TaskStatus = { task_id: taskId, status: 'pending' }
    get.mockResolvedValue({
      data: {
        task_id: taskId,
        status: 'failed',
        error: 'legacy',
        error_payload: { code: 'task_failed', stage: 'run_task', message: 'structured message' },
      } satisfies TaskStatus,
    })

    const error = await waitForTaskResult<RunTaskResult>(initial).catch((err) => err)

    expect(error).toBeInstanceOf(TaskFailureError)
    expect(error).toMatchObject({
      name: 'TaskFailureError',
      taskId,
      status: 'failed',
      errorPayload: { code: 'task_failed', stage: 'run_task', message: 'structured message' },
    })
  })


  it('keeps legacy failure message when structured payload is missing', async () => {
    const taskId = 'task-legacy-error'
    const initial: TaskStatus = { task_id: taskId, status: 'pending' }
    get.mockResolvedValue({
      data: {
        task_id: taskId,
        status: 'failed',
        error: 'legacy failure',
      } satisfies TaskStatus,
    })

    const error = await waitForTaskResult<RunTaskResult>(initial).catch((err) => err)

    expect(error).toBeInstanceOf(TaskFailureError)
    expect(error.message).toContain('legacy failure')
  })

  it('when both maxAttempts and timeoutMs are provided, fails by earlier timeoutMs limit', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2025-01-01T00:00:00Z'))

    const taskId = 'task-timeout-wins'
    const initial: TaskStatus = { task_id: taskId, status: 'pending' }

    get.mockResolvedValue({ data: { task_id: taskId, status: 'running' } satisfies TaskStatus })

    const promise = waitForTaskResult<RunTaskResult>(initial, {
      pollIntervalMs: 200,
      timeoutMs: 600,
      maxAttempts: 10,
    })
    const assertion = expect(promise).rejects.toThrow(
      /Client-side timeout while waiting for task result \(elapsedMs=600, pollIntervalMs=200, maxAttempts=10, timeoutMs=600\)/
    )

    await vi.advanceTimersByTimeAsync(600)

    await assertion
    expect(get).toHaveBeenCalledTimes(3)
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
      expect(url).toBe(`/tasks/status/${taskId}`)
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
