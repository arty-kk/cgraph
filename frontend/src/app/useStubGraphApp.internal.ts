// frontend/src/app/useStubGraphApp.internal.ts
// Pure types, constants and helpers extracted from useStubGraphApp (no React, no side effects).
import type { Mode, Project, SnapshotCreateTaskResult, FileSaveResult, TaskStatus } from '@/api'

export type AutoOrMode = 'auto' | Mode
export type GraphMode = 'local' | 'full' | 'limit'
export type RetrievalMode = 'agentic' | 'pack'
export type WorkspaceView = 'graph' | 'editor'

export type FileEditorEntry = {
  path: string
  content: string
  original: string
  dirty: boolean
  truncated: boolean
  busy: boolean
  saving: boolean
  loaded: boolean
  error: string | null
}

export type PendingFileJump = {
  path: string
  line: number
  column: number
}

export type WorkspaceStateV1 = {
  version: 1
  selectedPath: string | null
  pinnedPaths: string[]
  selectionTrail: string[]
  backStack: string[]
  forwardStack: string[]
  graphMode: GraphMode
  graphLimitN: number
  graphHops: number
  graphLocalMax: number
}

export type WorkspaceStateV2 = {
  version: 2
  selectedPath: string | null
  pinnedPaths: string[]
  selectionTrail: string[]
  backStack: string[]
  forwardStack: string[]
  graphMode: GraphMode
  graphLimitN: number
  graphHops: number
  graphLocalMax: number
  workspaceView: WorkspaceView
}

export type WorkspaceStateV3 = {
  version: 3
  selectedPath: string | null
  pinnedPaths: string[]
  selectionTrail: string[]
  backStack: string[]
  forwardStack: string[]
  graphMode: GraphMode
  graphLimitN: number
  graphHops: number
  graphLocalMax: number
  workspaceView: WorkspaceView
  openFilePaths: string[]
  activeFilePath: string | null
  fileEditorsByPath: Record<string, { dirty?: boolean }>
}

export const WORKSPACE_KEY_PREFIX = 'cs.workspace.v3.'
export const LEGACY_WORKSPACE_KEY_PREFIX = 'cs.workspace.v2.'
export const LEGACY_WORKSPACE_KEY_PREFIX_V1 = 'cs.workspace.v1.'

export function wsKey(projectId: number): string {
  return `${WORKSPACE_KEY_PREFIX}${projectId}`
}

export function legacyWsKey(projectId: number): string {
  return `${LEGACY_WORKSPACE_KEY_PREFIX}${projectId}`
}

export function legacyWsKeyV1(projectId: number): string {
  return `${LEGACY_WORKSPACE_KEY_PREFIX_V1}${projectId}`
}
export function draftKey(projectId: number): string {
  return `cs.drafts.v1.${projectId}`
}
export function isAnyModalOpen(): boolean {
  if (typeof document === 'undefined') return false
  const raw = document.body?.dataset?.csModalOpenCount
  const n = Number(raw ?? '0')
  return Number.isFinite(n) && n > 0
}

export function asStr(v: any): string {
  return typeof v === 'string' ? v.trim() : ''
}

export function asStrArr(v: any, limit = 400): string[] {
  if (!Array.isArray(v)) return []
  const out: string[] = []
  for (const x of v) {
    const s = asStr(x)
    if (!s) continue
    if (!out.includes(s)) out.push(s)
    if (out.length >= limit) break
  }
  return out
}

export function asInt(v: any, fallback: number, lo: number, hi: number): number {
  const n = Number(v)
  if (!Number.isFinite(n)) return fallback
  const i = Math.trunc(n)
  return Math.max(lo, Math.min(hi, i))
}

export function asWarnings(v: any): string[] {
  if (!Array.isArray(v)) return []
  return v.map((item) => String(item || '').trim()).filter(Boolean)
}

export function asGraphMode(v: any, fallback: GraphMode): GraphMode {
  const s = asStr(v)
  return s === 'local' || s === 'full' || s === 'limit' ? s : fallback
}

export function createFileEditorEntry(path: string, opts: { dirty?: boolean } = {}): FileEditorEntry {
  const dirty = Boolean(opts.dirty)
  return {
    path,
    content: '',
    original: '',
    dirty,
    truncated: false,
    busy: false,
    saving: false,
    loaded: false,
    error: null,
  }
}

export function isEntryDirty(entry: FileEditorEntry | null | undefined): boolean {
  return Boolean(entry && entry.content !== entry.original)
}

export function asNum(v: unknown): number | null {
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

export function pickCreatedSnapshotProject(
  projects: Project[],
  result: SnapshotCreateTaskResult | null | undefined,
): Project | null {
  const projectId = asNum(result?.project_id)
  if (projectId != null) {
    const byId = projects.find((project) => project.id === projectId)
    if (byId) return byId
  }
  const targetName = asStr(result?.name)
  if (!targetName) return null
  const sameName = projects.filter((project) => asStr(project.name) === targetName)
  if (!sameName.length) return null
  const snapshotLike = sameName.find((project) => {
    const sourceKind = asStr(project.source?.kind).toLowerCase()
    return sourceKind === 'snapshot' || sourceKind === 'archive'
  })
  return snapshotLike ?? sameName[0] ?? null
}


export const GRAPH_NOT_BUILT_WARNING = 'graph not built'

export function getRunGraphStaleState(warning: unknown): { stale: boolean; message: string | null } {
  if (typeof warning === 'string' && warning.trim().toLowerCase() === GRAPH_NOT_BUILT_WARNING) {
    return {
      stale: true,
      message: 'Graph index is not ready. Run Scan/Rescan now to refresh context.',
    }
  }
  return { stale: false, message: null }
}


export function getMutationTaskSeed(payload: FileSaveResult | null | undefined): TaskStatus | null {
  const taskId = asStr(payload?.task_id) || asStr(payload?.rescan_task?.task_id)
  if (!taskId) return null
  const rawStatus = asStr(payload?.task_status) || asStr(payload?.rescan_task?.status)
  const status: TaskStatus['status'] = rawStatus === 'running' ? 'running' : 'pending'
  return { task_id: taskId, status }
}

export type NotificationKind = 'info' | 'error'

export type NotificationItem = {
  id: string
  kind: NotificationKind
  text: string
}

export type IndexStatus = 'ok' | 'rescan_scheduled' | 'failed'

export type FileSaveBanner = {
  path: string
  status: IndexStatus
  warnings: string[]
  rollback?: string
  conflict?: boolean
  conflictReason?: string
  error?: string
  rescanTask?: { task_id?: string; status?: string }
  metricsPending?: boolean
}

export type DependencyMeta = {
  total_in: number
  total_out: number
  truncated_in: boolean
  truncated_out: boolean
  next_cursor_in?: string | null
  next_cursor_out?: string | null
  cursor_in?: string | null
  cursor_out?: string | null
}

export type DraftEntry = {
  content: string
  original: string
  updatedAt: number
}

export type UseStubGraphAppOptions = {
  onFocusSearch?: () => void
}


export type TaskBannerItem = {
  id: string
  kind: 'scan' | 'docs' | 'run'
  status: TaskStatus['status']
  label: string
  startedAt: number
  finishedAt?: number | null
  error?: string | null
}
