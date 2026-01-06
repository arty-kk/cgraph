// frontend/src/api/types.ts
export type Project = { id: number; name: string; root_path: string }

export type GraphMeta = {
  total_nodes: number
  total_edges: number
  returned_nodes: number
  returned_edges: number
  truncated: boolean
  limit_nodes: number
  auto_limit_threshold: number
}

export type GraphNode = {
  id: string
  label: string
  path: string
  language: string
  loc: number
  complexity: number
  fan_in: number
  fan_out: number
  scc_id: number
  status: string
  risk: number
}

export type GraphEdge = { source: string; target: string; kind: string }

export type GraphData = {
  nodes: GraphNode[]
  edges: GraphEdge[]
  meta?: GraphMeta
}

export type Mode = 'analyze' | 'evolve' | 'fix' | 'impact'
export type DepMode = 'contracts' | 'full'

export type RunTaskBody = {
  target_path: string
  prompt: string
  mode?: Mode
  depth?: number
  dep_mode?: DepMode
  apply_patch?: boolean
}

export type RunRecord = {
  id?: number | string
  run_id?: number | string
  created_at?: string
  target_path?: string
  prompt?: string
  mode?: string
}

export type RunDetails = {
  id: number
  project_id: number
  target_path: string
  mode: string
  prompt: string
  model_used: string
  created_at: string
  result: any
}