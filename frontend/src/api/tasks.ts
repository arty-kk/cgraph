// frontend/src/api/tasks.ts
import { api } from './client'
import type {
  RunDetails,
  RunRecord,
  RunTaskBody,
  RunTaskResult,
  TaskPollOptions,
  TaskStatus,
} from './types'

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
const successStatuses = new Set(['succeeded'])
const errorStatuses = new Set(['failed'])
const pendingStatuses = new Set(['pending', 'running'])

function isTaskStatus(payload: unknown): payload is TaskStatus {
  return (
    typeof payload === 'object' &&
    payload !== null &&
    typeof (payload as TaskStatus).task_id === 'string' &&
    typeof (payload as TaskStatus).status === 'string'
  )
}

export async function getTaskStatus(taskId: string): Promise<TaskStatus> {
  const r = await api.get(`/api/tasks/status/${taskId}`)
  return r.data
}

export async function waitForTaskResult<T>(
  payload: T | TaskStatus,
  opts: TaskPollOptions = {}
): Promise<T> {
  if (!isTaskStatus(payload)) return payload as T

  const pollInterval = Math.max(200, opts.pollIntervalMs ?? 1000)
  const maxAttempts = opts.maxAttempts ?? 120
  let attempt = 0
  let current: TaskStatus = payload

  while (attempt < maxAttempts) {
    if (successStatuses.has(current.status)) {
      return (current.result as T) ?? (current as unknown as T)
    }

    if (errorStatuses.has(current.status)) {
      const err = current.error ?? 'Task failed'
      const message = typeof err === 'string' ? err : JSON.stringify(err)
      throw new Error(message)
    }

    if (!pendingStatuses.has(current.status)) {
      throw new Error(`Unknown task status: ${current.status}`)
    }

    await delay(pollInterval)
    current = await getTaskStatus(current.task_id)
    attempt += 1
  }

  throw new Error('Task did not finish in time')
}

export async function runTask(
  projectId: number,
  body: RunTaskBody,
  opts: TaskPollOptions = {}
): Promise<RunTaskResult> {
  const background = opts.background ?? true
  const r = await api.post(`/api/tasks/${projectId}/run`, body, { params: { background } })
  return waitForTaskResult<RunTaskResult>(r.data, opts)
}

export async function runTaskStatus(
  projectId: number,
  body: RunTaskBody,
  opts: TaskPollOptions = {}
): Promise<RunTaskResult | TaskStatus> {
  const background = opts.background ?? true
  const r = await api.post(`/api/tasks/${projectId}/run`, body, { params: { background } })
  return r.data
}

export async function listRuns(projectId: number): Promise<RunRecord[]> {
  const r = await api.get(`/api/tasks/${projectId}/runs`)
  return r.data
}

export async function getRunPatch(projectId: number, runId: number): Promise<{ patch_unified_diff: string }> {
  const r = await api.get(`/api/tasks/${projectId}/runs/${runId}/patch`)
  return r.data
}

export async function applyRunPatch(
  projectId: number,
  runId: number
): Promise<{ applied: RunTaskResult['applied'] }> {
  const r = await api.post(`/api/tasks/${projectId}/runs/${runId}/apply`)
  return r.data
}

export async function getRun(projectId: number, runId: number): Promise<RunDetails> {
  const r = await api.get(`/api/tasks/${projectId}/runs/${runId}`)
  return r.data
}

export async function deleteRun(projectId: number, runId: number): Promise<{ ok: boolean }> {
  const r = await api.delete(`/api/tasks/${projectId}/runs/${runId}`)
  return r.data
}
