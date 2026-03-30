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
const asFiniteNumber = (value: number | undefined): number | undefined =>
  typeof value === 'number' && Number.isFinite(value) ? value : undefined
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
  const r = await api.get(`/tasks/status/${taskId}`)
  return r.data
}

/** Polling options apply only here when waiting for async task completion. */
export async function waitForTaskResult<T>(
  payload: T | TaskStatus,
  opts: TaskPollOptions = {}
): Promise<T> {
  if (!isTaskStatus(payload)) return payload as T

  const pollInterval = Math.max(200, asFiniteNumber(opts.pollIntervalMs) ?? 1000)
  const timeoutMs = Math.max(0, asFiniteNumber(opts.timeoutMs) ?? 30 * 60 * 1000)
  const startedAt = Date.now()
  const maxAttemptsRaw = asFiniteNumber(opts.maxAttempts)
  const maxAttempts = maxAttemptsRaw === undefined ? undefined : Math.max(0, maxAttemptsRaw)
  let attempt = 0
  let current: TaskStatus = payload

  while (true) {
    if (successStatuses.has(current.status)) {
      return (current.result as T) ?? (current as unknown as T)
    }

    if (errorStatuses.has(current.status)) {
      const payloadMessage =
        current.error_payload && typeof current.error_payload.message === 'string'
          ? current.error_payload.message
          : undefined
      const err = payloadMessage ?? current.error ?? 'Task failed'
      const message = typeof err === 'string' ? err : JSON.stringify(err)
      throw new Error(message)
    }

    if (!pendingStatuses.has(current.status)) {
      throw new Error(`Unknown task status: ${current.status}`)
    }

    const elapsedMs = Date.now() - startedAt
    const attemptsExhausted = maxAttempts !== undefined && attempt >= maxAttempts
    const timeoutExceeded = elapsedMs >= timeoutMs
    if (attemptsExhausted || timeoutExceeded) {
      throw new Error(
        `Client-side timeout while waiting for task result (elapsedMs=${elapsedMs}, pollIntervalMs=${pollInterval}, maxAttempts=${maxAttempts ?? 'none'}, timeoutMs=${timeoutMs})`
      )
    }

    await delay(pollInterval)
    current = await getTaskStatus(current.task_id)
    attempt += 1
  }
}

/** Starts a task and returns its initial status; polling is handled via waitForTaskResult. */
export async function runTask(
  projectId: number,
  body: RunTaskBody
): Promise<TaskStatus> {
  const r = await api.post(`/tasks/${projectId}/run`, body)
  return r.data
}


export async function listRuns(projectId: number): Promise<RunRecord[]> {
  const r = await api.get(`/tasks/${projectId}/runs`)
  return r.data
}

export async function getRunPatch(projectId: number, runId: number): Promise<{ patch_unified_diff: string }> {
  const r = await api.get(`/tasks/${projectId}/runs/${runId}/patch`)
  return r.data
}

export async function applyRunPatch(
  projectId: number,
  runId: number
): Promise<{ applied: RunTaskResult['applied'] }> {
  const r = await api.post(`/tasks/${projectId}/runs/${runId}/apply`)
  return r.data
}

export async function getRun(projectId: number, runId: number): Promise<RunDetails> {
  const r = await api.get(`/tasks/${projectId}/runs/${runId}`)
  return r.data
}

export async function deleteRun(projectId: number, runId: number): Promise<{ ok: boolean }> {
  const r = await api.delete(`/tasks/${projectId}/runs/${runId}`)
  return r.data
}
