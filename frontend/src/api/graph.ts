// frontend/src/api/graph.ts
import { api } from './client'
import type { GraphData } from './types'

export async function getGraph(projectId: number, limitNodes?: number | null): Promise<GraphData> {
  const params =
    typeof limitNodes === 'number' && Number.isFinite(limitNodes)
      ? { limit_nodes: limitNodes }
      : undefined
  const r = await api.get(`/api/projects/${projectId}/graph`, { params })
  return r.data
}
