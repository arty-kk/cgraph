// frontend/src/api/projects.ts
import { api } from './client'
import type { 
  Project, ScanResult, TaskPollOptions,
  TaskStatus, ProjectFilesResponse, ProjectDocs 
} from './types'
import { waitForTaskResult } from './tasks'

export async function listProjects(): Promise<Project[]> {
  const r = await api.get('/api/projects')
  return r.data
}

export async function createProject(name: string, root_path: string): Promise<Project> {
  const r = await api.post('/api/projects', { name, root_path })
  return r.data
}

export async function deleteProject(projectId: number): Promise<{ ok: boolean }> {
  const r = await api.delete(`/api/projects/${projectId}`)
  return r.data
}

export async function scanProject(projectId: number, opts: TaskPollOptions = {}): Promise<ScanResult> {
  const background = opts.background ?? true
  const r = await api.post(`/api/projects/${projectId}/scan`, null, { params: { background } })
  const initial = r.data as ScanResult | TaskStatus
  return waitForTaskResult<ScanResult>(initial, opts)
}

export async function listProjectFiles(projectId: number, prefix?: string, limit = 50_000): Promise<ProjectFilesResponse> {
  const params: any = { limit }
  if (typeof prefix === 'string' && prefix.trim()) params.prefix = prefix.trim()
  const r = await api.get(`/api/projects/${projectId}/files`, { params })
  return r.data
}

export async function getProjectDocs(projectId: number, kind = 'overview'): Promise<ProjectDocs> {
  const r = await api.get(`/api/projects/${projectId}/docs`, { params: { kind } })
  return r.data
}

export async function buildProjectDocs(projectId: number, opts: TaskPollOptions = {}): Promise<ProjectDocs> {
  const background = opts.background ?? true
  const r = await api.post(`/api/projects/${projectId}/docs/build`, null, { params: { background } })
  return waitForTaskResult<ProjectDocs>(r.data, opts)
}
