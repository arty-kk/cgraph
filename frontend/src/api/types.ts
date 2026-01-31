// frontend/src/api/types.ts
export type Project = { id: number; name: string; root_path: string }

export type AgenticRetrievalSettings = {
  complexity_coeff?: number
  complexity_inputs?: {
    depth?: number
    prompt_len?: number
    project_nodes?: number
    mode?: string
  }
  budget_reason?: string[]
  max_calls?: number
  max_file_chars?: number
  max_total_tool_output_chars?: number
  temperature?: number
  reasoning_effort?: string
  agentic_evidence_mode?: boolean
  self_check_ok?: boolean
  self_check_notes?: string[]
  self_check_missing_context?: string[]
  self_check_retry?: boolean
  self_check_retry_reason?: string | null
  self_check_retry_missing_context?: string[]
  self_check_retry_multiplier?: {
    max_calls?: number
    max_total_tool_output_chars?: number
    max_file_chars?: number
  }

  tool_calls_used?: number
  tool_output_chars_used?: number
  cache_hits?: number
  files_read?: number
  tool_trace?: {
    name?: string
    args?: Record<string, unknown>
    cache_hit?: boolean
    response_chars?: number
    duration_ms?: number
    status?: 'ok' | 'error' | string
  }[]
}

export type PackRetrievalSettings = {
  max_files?: number
  max_chars_per_file?: number
  max_total_chars?: number
}

export type GraphRetrievalSettings = {
  max_nodes?: number | null
  max_depth?: number | null
  truncated?: boolean
}

export type RetrievalSettings = {
  agentic?: AgenticRetrievalSettings
  pack?: PackRetrievalSettings
  graph?: GraphRetrievalSettings
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
  allow_out_of_context_patch?: boolean
  agentic: boolean

  pack_max_files?: number
  pack_max_chars_per_file?: number
  pack_max_total_chars?: number

  agentic_max_calls?: number
  agentic_max_file_chars?: number
  agentic_max_total_tool_output_chars?: number
  agentic_temperature?: number
  agentic_reasoning_effort?: string
  agentic_evidence_mode?: boolean
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

export type SemanticSearchItem = {
  path: string
  score: number
  snippet: string
  meta?: Record<string, unknown>
}

export type SemanticSearchResult = {
  query: string
  prefix?: string
  results: SemanticSearchItem[]
  meta?: {
    compared?: number
    total_candidates?: number
    max_candidates?: number
    max_results?: number
    returned?: number
    truncated?: boolean
    reason?: string
  }
}

export type TextSearchMatch = {
  path: string
  line: number
  col: number
  snippet: string
  truncated_file: boolean
}

export type TextSearchResult = {
  matches: TextSearchMatch[]
  meta: {
    query: string
    prefix: string
    case_sensitive: boolean
    limit_files: number
    limit_matches: number
    context_chars: number
    scan_max_chars_per_file?: number
    scanned_files: number
    matched_files: number
    truncated_files: number
    message?: string
  }
}

export type PlanTz = {
  summary: string
  requirements: string[]
  constraints: string[]
  sdlc_plan: string[]
  acceptance_criteria: string[]
  risks: string[]
  open_questions: string[]
  deliverables: string[]
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
    blocked_paths?: string[]
    blocked_reason?: 'out_of_context'
  } | null
  created_at: string
  result: unknown
  warning?: string | null
  graph_scan_task_id?: string | null
  graph_scan_status?: 'pending' | 'running' | 'succeeded' | 'failed' | null
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
  plan_tz?: PlanTz
  plan_source?: 'pack' | 'agentic' | 'graph' | 'skipped' | string
  applied?: {
    modified?: string[] | string
    reindexed?: unknown
    contracts_updated?: string[]
    contracts_removed?: string[]
    error?: string
    blocked_paths?: string[]
    blocked_reason?: 'out_of_context'
  }
  warning?: string | null
  graph_scan_task_id?: string | null
  graph_scan_status?: 'pending' | 'running' | 'succeeded' | 'failed' | null
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
