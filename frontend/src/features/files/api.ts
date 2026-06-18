// frontend/src/api/nodes.ts
import { api } from '@/shared/api/client'
import type { FileContent, FileSaveResult, NodeContract, NodeInfo } from '@/shared/types'
import { encodePath } from '@/shared/api/utils'

export async function getNode(projectId: number, path: string): Promise<NodeInfo> {
  const r = await api.get(`/nodes/${projectId}/${encodePath(path)}/node`)
  return r.data as NodeInfo
}

export async function getContract(projectId: number, path: string): Promise<NodeContract> {
  const r = await api.get(`/nodes/${projectId}/${encodePath(path)}/contract`)
  return r.data
}

export async function getFileContent(projectId: number, path: string, maxChars?: number): Promise<FileContent> {
  const r = await api.get(`/nodes/${projectId}/${encodePath(path)}/file`, {
    params: typeof maxChars === 'number' ? { max_chars: maxChars } : undefined,
  })
  return r.data
}

export async function updateFileContent(projectId: number, path: string, content: string): Promise<FileSaveResult> {
  const r = await api.put(`/nodes/${projectId}/${encodePath(path)}/file`, { content })
  return r.data
}

export async function createFile(projectId: number, path: string, content?: string): Promise<FileSaveResult> {
  const r = await api.post(`/nodes/${projectId}/${encodePath(path)}/file`, { content })
  return r.data
}

export async function renameFile(
  projectId: number,
  path: string,
  newPath: string,
  createDirs?: boolean,
): Promise<FileSaveResult> {
  const r = await api.post(`/nodes/${projectId}/${encodePath(path)}/rename`, {
    new_path: newPath,
    create_dirs: createDirs,
  })
  return r.data
}

export async function deleteFile(projectId: number, path: string): Promise<FileSaveResult> {
  const r = await api.delete(`/nodes/${projectId}/${encodePath(path)}/file`)
  return r.data
}
