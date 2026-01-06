// frontend/src/api/tasks.ts
import { api } from './client'
import type { RunRecord, RunTaskBody, RunDetails } from './types'

export async function runTask(projectId: number, body: RunTaskBody): Promise<any> {
  const r = await api.post(`/api/tasks/${projectId}/run`, body)
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

export async function getRun(projectId: number, runId: number): Promise<RunDetails> {
  const r = await api.get(`/api/tasks/${projectId}/runs/${runId}`)
  return r.data
}