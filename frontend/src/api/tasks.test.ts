import { describe, expect, it, vi } from 'vitest'
import type { RunTaskBody, RunTaskResult, TaskStatus } from './types'

const { post, get } = vi.hoisted(() => ({
  post: vi.fn(),
  get: vi.fn(),
}))

vi.mock('./client', () => ({
  api: { post, get },
}))

import { runTask, waitForTaskResult } from './tasks'

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
})
