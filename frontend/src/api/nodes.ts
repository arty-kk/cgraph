// frontend/src/api/nodes.ts
import { api } from './client'
import type { FileContent, FileSaveResult, NodeContract, NodeInfo } from './types'
import { encodePath } from './utils'

export async function getNode(projectId: number, path: string): Promise<NodeInfo> {
  const r = await api.get(`/api/nodes/${projectId}/${encodePath(path)}/node`)
  return r.data
}

export async function getContract(projectId: number, path: string): Promise<NodeContract> {
  const r = await api.get(`/api/nodes/${projectId}/${encodePath(path)}/contract`)
  return r.data
}

export async function getFileContent(projectId: number, path: string, maxChars?: number): Promise<FileContent> {
  const r = await api.get(`/api/nodes/${projectId}/${encodePath(path)}/file`, {
    params: typeof maxChars === 'number' ? { max_chars: maxChars } : undefined,
  })
  return r.data
}

export async function updateFileContent(projectId: number, path: string, content: string): Promise<FileSaveResult> {
  const r = await api.put(`/api/nodes/${projectId}/${encodePath(path)}/file`, { content })
  return r.data
}
