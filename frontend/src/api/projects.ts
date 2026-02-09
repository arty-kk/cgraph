// frontend/src/api/projects.ts
import { api } from './client'
import type {
  Project,
  ScanResult,
  TaskPollOptions,
  TaskStatus,
  ProjectFilesResponse,
  ProjectDocs,
  ProjectTreeResponse,
  FileDependenciesResponse,
  SemanticSearchResult,
  TextSearchResult,
} from './types'
import { waitForTaskResult } from './tasks'

export async function listProjects(): Promise<Project[]> {
  const r = await api.get('/api/projects')
  return r.data
}

export async function createProjectFromSnapshot(name: string, archive: File): Promise<Project> {
  const data = new FormData()
  data.append('name', name)
  data.append('archive', archive)
  const r = await api.post('/api/projects/from-snapshot', data)
  return r.data
}

export async function createProjectFromRoot(name: string, root_path: string): Promise<Project> {
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

export async function scanProjectStatus(
  projectId: number,
  opts: TaskPollOptions = {},
): Promise<ScanResult | TaskStatus> {
  const background = opts.background ?? true
  const r = await api.post(`/api/projects/${projectId}/scan`, null, { params: { background } })
  return r.data
}

export async function listProjectFiles(projectId: number, prefix?: string, limit = 2_000): Promise<ProjectFilesResponse> {
  const params: any = { limit }
  if (typeof prefix === 'string' && prefix.trim()) params.prefix = prefix.trim()
  const r = await api.get(`/api/projects/${projectId}/files`, { params })
  return r.data
}

export async function listProjectTreeEntries(
  projectId: number,
  opts: { prefix?: string; cursor?: string; limit?: number } = {},
): Promise<ProjectTreeResponse> {
  const params: Record<string, any> = {}
  if (typeof opts.prefix === 'string' && opts.prefix.trim()) params.prefix = opts.prefix.trim()
  if (typeof opts.cursor === 'string' && opts.cursor.trim()) params.cursor = opts.cursor.trim()
  if (typeof opts.limit === 'number') params.limit = opts.limit
  const r = await api.get(`/api/projects/${projectId}/files/tree`, { params })
  return r.data
}

export async function getFileDependencies(
  projectId: number,
  path: string,
  limit = 2000,
): Promise<FileDependenciesResponse> {
  const params: Record<string, any> = { path, limit }
  const r = await api.get(`/api/projects/${projectId}/dependencies`, { params })
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

export async function buildProjectDocsStatus(
  projectId: number,
  opts: TaskPollOptions = {},
): Promise<ProjectDocs | TaskStatus> {
  const background = opts.background ?? true
  const r = await api.post(`/api/projects/${projectId}/docs/build`, null, { params: { background } })
  return r.data
}

export async function searchProjectSemantic(
  projectId: number,
  q: string,
  limit = 20,
  prefix?: string,
): Promise<SemanticSearchResult> {
  const params: Record<string, any> = { q, limit }
  if (typeof prefix === 'string' && prefix.trim()) params.prefix = prefix.trim()
  const r = await api.get(`/api/projects/${projectId}/search/semantic`, { params })
  return r.data
}

export async function searchProjectText(
  projectId: number,
  q: string,
  opts: {
    limit_files?: number
    limit_matches?: number
    context_chars?: number
    prefix?: string
    case_sensitive?: boolean
  } = {},
): Promise<TextSearchResult> {
  const {
    limit_files = 200,
    limit_matches = 50,
    context_chars = 160,
    prefix,
    case_sensitive,
  } = opts
  const params: Record<string, any> = { q, limit_files, limit_matches, context_chars }
  if (typeof prefix === 'string' && prefix.trim()) params.prefix = prefix.trim()
  if (case_sensitive) params.case_sensitive = true
  const r = await api.get(`/api/projects/${projectId}/search/text`, { params })
  return r.data
}
