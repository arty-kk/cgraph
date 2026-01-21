// frontend/src/api/types.ts
export type Project = { id: number; name: string; root_path: string }

export type AgenticRetrievalSettings = {
  max_calls?: number
  max_file_chars?: number
  max_total_tool_output_chars?: number
  temperature?: number

  tool_calls_used?: number
  tool_output_chars_used?: number
  cache_hits?: number
  files_read?: number
}

export type PackRetrievalSettings = {
  max_files?: number
  max_chars_per_file?: number
  max_total_chars?: number
}

export type RetrievalSettings = {
  agentic?: AgenticRetrievalSettings
  pack?: PackRetrievalSettings
  graph?: Record<string, any>
}

export type GraphMeta = {
  total_nodes?: number
  total_edges?: number
  returned_nodes?: number
  returned_edges?: number
  truncated?: boolean
  limit_nodes?: number
  auto_limit_threshold?: number
  center?: string
  found?: boolean
  hops?: number
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

export type NodeInfo = {
  path: string
  language: string
  loc: number
  fan_in: number
  fan_out: number
  complexity: number
  scc_id: number
  status: string
}

export type NodeContract = Record<string, unknown>
export type FileContent = { path: string; content: string; truncated?: boolean; max_chars?: number | null }
export type FileSaveResult = { path: string; saved: boolean; reindexed?: unknown }

export type Mode = 'analyze' | 'evolve' | 'fix' | 'impact'
export type DepMode = 'contracts' | 'full'

export type RunTaskBody = {
  target_path: string
  prompt: string
  mode?: Mode
  depth?: number
  dep_mode?: DepMode
  apply_patch?: boolean
  agentic: boolean

  pack_max_files?: number
  pack_max_chars_per_file?: number
  pack_max_total_chars?: number

  agentic_max_calls?: number
  agentic_max_file_chars?: number
  agentic_max_total_tool_output_chars?: number
  agentic_temperature?: number
}

export type RunRecord = {
  id: number
  created_at: string
  target_path: string
  prompt: string
  mode: string
  model_used: string
}

export type NodeSearchItem = {
  path: string
  language?: string
  fan_in?: number
  fan_out?: number
}

export type RunDetails = {
  id: number
  project_id: number
  target_path: string
  mode: string
  prompt: string
  model_used: string
  depth?: number | null
  dep_mode?: DepMode | string | null
  retrieval?: 'agentic' | 'pack' | 'graph' | string | null
  retrieval_settings?: RetrievalSettings
  apply_patch?: boolean | null
  applied?: {
    modified?: string[] | string
    reindexed?: unknown
    contracts_updated?: string[]
    contracts_removed?: string[]
    error?: string
  } | null
  created_at: string
  result: unknown
}

export type RunTaskResult = {
  run_id: number
  mode: Mode | string
  depth?: number
  dep_mode?: DepMode | string
  retrieval?: 'agentic' | 'pack' | 'graph' | string
  retrieval_settings?: RetrievalSettings
  apply_patch?: boolean | null
  result: unknown
  applied?: {
    modified?: string[] | string
    reindexed?: unknown
    contracts_updated?: string[]
    contracts_removed?: string[]
    error?: string
  }
}

export type TaskStatus = {
  task_id: string
  status: 'pending' | 'running' | 'succeeded' | 'failed'
  error?: unknown
  result?: unknown
}

export type TaskPollOptions = {
  background?: boolean
  pollIntervalMs?: number
  maxAttempts?: number
}

export type ScanResult = { ok: boolean; stats?: unknown }

export type ProjectFileItem = {
  path: string
  language: string
  loc: number
  complexity: number
  fan_in: number
  fan_out: number
  status: string
  risk: number
}

export type ProjectFilesResponse = {
  files: ProjectFileItem[]
  meta: { prefix?: string; total: number; returned: number; truncated: boolean; limit: number }
}

export type ProjectDocs = {
  project_id: number
  kind: string
  created_at: string
  markdown: string
}
