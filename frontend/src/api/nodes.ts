// frontend/src/api/nodes.ts
import { api } from './client'
import type { NodeContract, NodeInfo } from './types'
import { encodePath } from './utils'

export async function getNode(projectId: number, path: string): Promise<NodeInfo> {
  const r = await api.get(`/api/nodes/${projectId}/${encodePath(path)}/node`)
  return r.data
}

export async function getContract(projectId: number, path: string): Promise<NodeContract> {
  const r = await api.get(`/api/nodes/${projectId}/${encodePath(path)}/contract`)
  return r.data
}
