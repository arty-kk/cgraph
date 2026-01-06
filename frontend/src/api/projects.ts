// frontend/src/api/projects.ts
import { api } from './client'
import type { Project } from './types'

export async function listProjects(): Promise<Project[]> {
  const r = await api.get('/api/projects')
  return r.data
}

export async function createProject(name: string, root_path: string): Promise<Project> {
  const r = await api.post('/api/projects', { name, root_path })
  return r.data
}

export async function scanProject(projectId: number): Promise<any> {
  const r = await api.post(`/api/projects/${projectId}/scan`)
  return r.data
}
