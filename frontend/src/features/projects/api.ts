// frontend/src/api/projects.ts
import { api } from '@/shared/api/client'
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
} from '@/shared/types'
import { waitForTaskResult } from '@/features/analysis/api'

export async function listProjects(): Promise<Project[]> {
  const r = await api.get('/projects')
  return r.data
}

export async function createProjectFromSnapshot(name: string, archive: File): Promise<TaskStatus> {
  const data = new FormData()
  data.append('name', name)
  data.append('archive', archive)
  const r = await api.post('/projects/from-snapshot', data)
  return r.data
}

export async function createProjectFromRoot(name: string, root_path: string): Promise<Project> {
  const r = await api.post('/projects', { name, root_path })
  return r.data
}

export async function deleteProject(projectId: number): Promise<{ ok: boolean }> {
  const r = await api.delete(`/projects/${projectId}`)
  return r.data
}

export async function scanProject(projectId: number, opts: TaskPollOptions = {}): Promise<ScanResult> {
  const initial = await scanProjectStatus(projectId, opts)
  return waitForTaskResult<ScanResult>(initial, opts)
}

export async function scanProjectStatus(
  projectId: number,
  opts: TaskPollOptions = {},
): Promise<TaskStatus> {
  void opts
  const r = await api.post(`/projects/${projectId}/scan`)
  return r.data
}

export async function listProjectFiles(
  projectId: number,
  opts: { prefix?: string; cursor?: string; limit?: number } = {},
): Promise<ProjectFilesResponse> {
  const params: any = { limit: opts.limit ?? 2_000 }
  if (typeof opts.prefix === 'string' && opts.prefix.trim()) params.prefix = opts.prefix.trim()
  if (typeof opts.cursor === 'string' && opts.cursor.trim()) params.cursor = opts.cursor.trim()
  const r = await api.get(`/projects/${projectId}/files`, { params })
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
  const r = await api.get(`/projects/${projectId}/files/tree`, { params })
  return r.data
}

export async function getFileDependencies(
  projectId: number,
  path: string,
  opts: { limit?: number; cursorIn?: string; cursorOut?: string } = {},
): Promise<FileDependenciesResponse> {
  const params: Record<string, any> = { path, limit: opts.limit ?? 2000 }
  if (typeof opts.cursorIn === 'string' && opts.cursorIn.trim()) params.cursor_in = opts.cursorIn.trim()
  if (typeof opts.cursorOut === 'string' && opts.cursorOut.trim()) params.cursor_out = opts.cursorOut.trim()
  const r = await api.get(`/projects/${projectId}/dependencies`, { params })
  return r.data
}

export async function getProjectDocs(projectId: number, kind = 'overview'): Promise<ProjectDocs> {
  const r = await api.get(`/projects/${projectId}/docs`, { params: { kind } })
  return r.data
}

export async function buildProjectDocs(projectId: number, opts: TaskPollOptions = {}): Promise<ProjectDocs> {
  const initial = await buildProjectDocsStatus(projectId, opts)
  return waitForTaskResult<ProjectDocs>(initial, opts)
}

export async function buildProjectDocsStatus(
  projectId: number,
  opts: TaskPollOptions = {},
): Promise<TaskStatus> {
  void opts
  const r = await api.post(`/projects/${projectId}/docs/build`)
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
  const r = await api.get(`/projects/${projectId}/search/semantic`, { params })
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
  const r = await api.get(`/projects/${projectId}/search/text`, { params })
  return r.data
}
