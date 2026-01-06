// frontend/src/api/nodes.ts
import { api } from './client'
import { encodePath } from './utils'

export async function getNode(projectId: number, path: string): Promise<any> {
  const r = await api.get(`/api/nodes/${projectId}/${encodePath(path)}/node`)
  return r.data
}

export async function getContract(projectId: number, path: string): Promise<any> {
  const r = await api.get(`/api/nodes/${projectId}/${encodePath(path)}/contract`)
  return r.data
}
