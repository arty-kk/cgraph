import type { TaskStatus } from './types'

export type TaskFailurePayload = {
  code?: string
  message?: string
  context?: Record<string, unknown>
  stage?: string
}

export function isTaskStatus(payload: unknown): payload is TaskStatus {
  return (
    typeof payload === 'object' &&
    payload !== null &&
    typeof (payload as TaskStatus).task_id === 'string' &&
    typeof (payload as TaskStatus).status === 'string'
  )
}

function stringifyTaskError(error: unknown): string | null {
  if (typeof error === 'string' && error.trim()) return error
  if (error == null) return null
  try {
    const text = JSON.stringify(error)
    return typeof text === 'string' && text ? text : null
  } catch {
    return String(error)
  }
}

function toFailurePayload(errorPayload: TaskStatus['error_payload']): TaskFailurePayload | undefined {
  if (!errorPayload || typeof errorPayload !== 'object') return undefined
  return {
    code: typeof errorPayload.code === 'string' ? errorPayload.code : undefined,
    message: typeof errorPayload.message === 'string' ? errorPayload.message : undefined,
    stage: typeof errorPayload.stage === 'string' ? errorPayload.stage : undefined,
    context:
      errorPayload.context && typeof errorPayload.context === 'object'
        ? errorPayload.context
        : undefined,
  }
}

function buildTaskFailureMessage(status: TaskStatus, payload: TaskFailurePayload | undefined): string {
  const fallbackError = stringifyTaskError(status.error)
  const message = payload?.message ?? fallbackError ?? 'Task failed'
  const code = payload?.code
  const stage = payload?.stage
  if (!code && !stage) return message
  const parts = [code, stage].filter((part): part is string => typeof part === 'string' && part.length > 0)
  if (parts.length === 0) return message
  return `[${parts.join(' @ ')}] ${message}`
}

export class TaskFailureError extends Error {
  readonly taskId: string
  readonly status: TaskStatus['status']
  readonly errorPayload?: TaskFailurePayload
  readonly rawError?: unknown

  constructor(task: TaskStatus) {
    const errorPayload = toFailurePayload(task.error_payload)
    super(buildTaskFailureMessage(task, errorPayload))
    this.name = 'TaskFailureError'
    this.taskId = task.task_id
    this.status = task.status
    this.errorPayload = errorPayload
    this.rawError = task.error
  }
}
