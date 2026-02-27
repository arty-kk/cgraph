// frontend/src/api/graph.ts
import { api } from './client'
import type { GraphData, NodeSearchItem } from './types'

export async function getGraph(projectId: number, limitNodes?: number | null): Promise<GraphData> {
  const params =
    typeof limitNodes === 'number' && Number.isFinite(limitNodes)
      ? { limit_nodes: limitNodes }
      : undefined
  const r = await api.get(`/projects/${projectId}/graph`, { params })
  return r.data
}

export async function getLocalGraph(
  projectId: number,
  path: string,
  hops = 1,
  maxNodes = 400,
  maxEdges = 800,
): Promise<GraphData> {
  const params: Record<string, any> = { path, hops, max_nodes: maxNodes, max_edges: maxEdges }
  const r = await api.get(`/projects/${projectId}/graph/local`, { params })
  return r.data
}

export async function searchNodes(projectId: number, query: string, limit = 20): Promise<NodeSearchItem[]> {
  const params = { q: query, limit }
  const r = await api.get(`/projects/${projectId}/search`, { params })
  return r.data
}
