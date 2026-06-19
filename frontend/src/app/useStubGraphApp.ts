// frontend/src/ui/useStubGraphApp.ts
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  listOrgs,
  getContract,
  getGraph,
  getLocalGraph,
  getNode,
  listProjects,
  listRuns,
  getTaskStatus,
  waitForTaskResult,
  getFileDependencies,
  getProjectDocs,
  buildProjectDocsStatus,
  getAppConfig,
  type DepMode,
  type GraphData,
  type GraphNode,
  type Mode,
  type NodeContract,
  type NodeInfo,
  type Org,
  type Project,
  type RunRecord,
  type RunTaskResult,
  isTaskStatus,
  type TaskStatus,
  type ProjectFileItem,
  type ProjectTreeEntry,
  type ProjectDocs,
  setSelectedOrgId,
} from '@/api'
import { extractError, getAppErrorInfo } from '@/shared/lib/errors'
import { clampInt } from '@/shared/lib/number'
import { useGraphSearch } from './useGraphSearch'
import { useAppConfig } from './useAppConfig'
import { useNotifications } from './useNotifications'
import { useGlobalKeyboard } from './useGlobalKeyboard'
import { useGraphRunActions } from './useGraphRunActions'
import { useFileEditors } from './useFileEditors'
import { useProjectActions } from './useProjectActions'
import { useFileTabs } from './useFileTabs'
import { useSelectionNav } from './useSelectionNav'
import {
  addStorageErrorListener,
  safeStorageGet,
  safeStorageGetJson,
  safeStorageRemove,
  safeStorageSet,
} from '@/shared/lib/storage'
import {
  WORKSPACE_KEY_PREFIX,
  LEGACY_WORKSPACE_KEY_PREFIX,
  LEGACY_WORKSPACE_KEY_PREFIX_V1,
  GRAPH_NOT_BUILT_WARNING,
  wsKey,
  legacyWsKey,
  legacyWsKeyV1,
  draftKey,
  asStr,
  asStrArr,
  asInt,
  asGraphMode,
  createFileEditorEntry,
  isEntryDirty,
  asNum,
  pickCreatedSnapshotProject,
  getRunGraphStaleState,
  getMutationTaskSeed,
} from './useStubGraphApp.internal'
import type {
  GraphMode,
  WorkspaceView,
  FileEditorEntry,
  PendingFileJump,
  WorkspaceStateV1,
  WorkspaceStateV2,
  WorkspaceStateV3,
  NotificationKind,
  NotificationItem,
  IndexStatus,
  FileSaveBanner,
  DependencyMeta,
  DraftEntry,
  UseStubGraphAppOptions,
} from './useStubGraphApp.internal'

// Preserve the existing public surface for external consumers (Notifications, tests).
export type {
  FileEditorEntry,
  PendingFileJump,
  NotificationKind,
  NotificationItem,
} from './useStubGraphApp.internal'
export {
  GRAPH_NOT_BUILT_WARNING,
  pickCreatedSnapshotProject,
  getRunGraphStaleState,
  getMutationTaskSeed,
} from './useStubGraphApp.internal'

export function useStubGraphApp(options: UseStubGraphAppOptions = {}) {
  const { onFocusSearch } = options
  const workspaceBootingRef = useRef(false)
  const workspaceSaveTimerRef = useRef<number | null>(null)
  const draftSaveTimerRef = useRef<number | null>(null)
  const restoredEditorRef = useRef(false)
  const draftPromptedRef = useRef<Set<string>>(new Set())

  const queryClient = useQueryClient()

  const ORG_STORAGE_KEY = 'cs.org.id'

  const orgsQuery = useQuery<Org[]>({
    queryKey: ['orgs'],
    queryFn: listOrgs,
    initialData: [],
  })

  const configQuery = useQuery({
    queryKey: ['config'],
    queryFn: getAppConfig,
    staleTime: 60_000,
  })

  const [selectedOrgId, setSelectedOrgIdState] = useState<number | null>(null)
  const prevOrgIdRef = useRef<number | null>(null)
  const [orgSelectionStorageFailureMarker, setOrgSelectionStorageFailureMarker] = useState(0)

  const applyOrgSelection = useCallback((orgId: number | null) => {
    setSelectedOrgId(orgId)
    const persisted = orgId == null
      ? safeStorageRemove(ORG_STORAGE_KEY)
      : safeStorageSet(ORG_STORAGE_KEY, String(orgId))
    if (!persisted) {
      setOrgSelectionStorageFailureMarker((prev) => prev + 1)
    }
    setSelectedOrgIdState(orgId)
  }, [])

  const [activeProject, setActiveProject] = useState<Project | null>(null)

  const nodeSeqRef = useRef(0)

  const [newName, setNewName] = useState('my-project')
  const [newArchive, setNewArchive] = useState<File | null>(null)
  const [newPath, setNewPath] = useState('')

  const [graphMode, setGraphMode] = useState<GraphMode>('limit')
  const [graphLimitN, setGraphLimitN] = useState<number>(2000)
  const [graphHops, setGraphHops] = useState<number>(2)
  const [graphLocalMax, setGraphLocalMax] = useState<number>(400)

  const [gotoLineRequestId, setGotoLineRequestId] = useState(0)
  const [findRequestId, setFindRequestId] = useState(0)
  const [replaceRequestId, setReplaceRequestId] = useState(0)
  const [outlineRequestId, setOutlineRequestId] = useState(0)

  const orgs = orgsQuery.data ?? []
  const allowLocalRootPath = configQuery.data?.allow_local_root_path ?? null

  useEffect(() => {
    if (orgs.length === 0) {
      if (selectedOrgId !== null) applyOrgSelection(null)
      return
    }

    if (selectedOrgId !== null && orgs.some((org) => org.id === selectedOrgId)) return

    let storedId: number | null = null
    const raw = safeStorageGet(ORG_STORAGE_KEY)
    const n = Number(raw)
    if (Number.isFinite(n)) storedId = Math.trunc(n)

    if (storedId !== null && orgs.some((org) => org.id === storedId)) {
      applyOrgSelection(storedId)
      return
    }

    if (orgs.length === 1) {
      applyOrgSelection(orgs[0].id)
      return
    }

    applyOrgSelection(null)
  }, [applyOrgSelection, orgs, selectedOrgId])

  const selectedPathRef = useRef<string | null>(null)
  const prevActiveFilePathRef = useRef<string | null>(null)
  const backStackRef = useRef<string[]>([])
  const forwardStackRef = useRef<string[]>([])
  const selectionTrailRef = useRef<string[]>([])

  const [backStack, setBackStack] = useState<string[]>([])
  const [forwardStack, setForwardStack] = useState<string[]>([])
  const [selectionTrail, setSelectionTrail] = useState<string[]>([])

  const [pinnedPaths, setPinnedPaths] = useState<string[]>([])
  const PIN_LIMIT = 3

  const [selectedPath, setSelectedPath] = useState<string | null>(null)

  useEffect(() => { selectedPathRef.current = selectedPath }, [selectedPath])
  useEffect(() => { backStackRef.current = backStack }, [backStack])
  useEffect(() => { forwardStackRef.current = forwardStack }, [forwardStack])
  useEffect(() => { selectionTrailRef.current = selectionTrail }, [selectionTrail])

  const [paletteOpen, setPaletteOpen] = useState(false)
  const [nodeInfo, setNodeInfo] = useState<NodeInfo | null>(null)
  const [contract, setContract] = useState<NodeContract | null>(null)
  const config = useAppConfig()
  const {
    mode, setMode, depth, setDepth, depMode, setDepMode, retrievalMode, setRetrievalMode,
    agenticMaxCalls, setAgenticMaxCalls, agenticMaxFileChars, setAgenticMaxFileChars,
    agenticMaxTotalToolOutputChars, setAgenticMaxTotalToolOutputChars,
    agenticTemperature, setAgenticTemperature, agenticEvidenceMode, setAgenticEvidenceMode,
    packMaxFiles, setPackMaxFiles, packMaxCharsPerFile, setPackMaxCharsPerFile,
    packMaxTotalChars, setPackMaxTotalChars,
  } = config

  const [applyPatch, setApplyPatch] = useState(false)
  const [prompt, setPrompt] = useState('')

  const [runResult, setRunResult] = useState<RunTaskResult | null>(null)
  const [fullPatch, setFullPatch] = useState<string | null>(null)
  const [patchBusy, setPatchBusy] = useState(false)
  const [runLoadBusy, setRunLoadBusy] = useState(false)
  const [busyCount, setBusyCount] = useState(0)
  const busy = busyCount > 0
  const {
    error, notifications, dismissNotification, pushNotification,
    notifyError, setErrorMessage, notifyInfo,
  } = useNotifications()
  const [focusGraph, setFocusGraph] = useState(false)

  type TaskBannerItem = {
    id: string
    kind: 'scan' | 'docs' | 'run'
    status: TaskStatus['status']
    label: string
    startedAt: number
    finishedAt?: number | null
    error?: string | null
  }

  const [taskStatuses, setTaskStatuses] = useState<TaskBannerItem[]>([])
  const taskStatusesRef = useRef<TaskBannerItem[]>([])
  useEffect(() => {
    taskStatusesRef.current = taskStatuses
  }, [taskStatuses])

  const [compactMode, setCompactMode] = useState<boolean>(() => (safeStorageGet('cs.ui.compactMode', '0') || '0') === '1')
  useEffect(() => {
    safeStorageSet('cs.ui.compactMode', compactMode ? '1' : '0')
  }, [compactMode])
  const toggleCompactMode = useCallback(() => setCompactMode((v) => !v), [])

  const [leftPanelOpen, setLeftPanelOpen] = useState<boolean>(() => (safeStorageGet('cs.ui.leftPanelOpen', '1') || '1') !== '0')
  const [rightPanelOpen, setRightPanelOpen] = useState<boolean>(() => (safeStorageGet('cs.ui.rightPanelOpen', '1') || '1') !== '0')
  useEffect(() => { safeStorageSet('cs.ui.leftPanelOpen', leftPanelOpen ? '1' : '0') }, [leftPanelOpen])
  useEffect(() => { safeStorageSet('cs.ui.rightPanelOpen', rightPanelOpen ? '1' : '0') }, [rightPanelOpen])

  const toggleLeftPanel = useCallback(() => setLeftPanelOpen((v) => !v), [])
  const toggleRightPanel = useCallback(() => setRightPanelOpen((v) => !v), [])
  
  const [workspaceView, setWorkspaceViewState] = useState<WorkspaceView>('graph')
  const [openFilePaths, setOpenFilePaths] = useState<string[]>([])
  const [fileEditorsByPath, setFileEditorsByPath] = useState<Record<string, FileEditorEntry>>({})
  const [activeFilePath, setActiveFilePath] = useState<string | null>(null)
  const [fileDependencies, setFileDependencies] = useState<{ in: string[]; out: string[] } | null>(null)
  const [fileDependenciesMeta, setFileDependenciesMeta] = useState<DependencyMeta | null>(null)
  const [fileDependenciesBusy, setFileDependenciesBusy] = useState(false)
  const [fileSaveBanner, setFileSaveBanner] = useState<FileSaveBanner | null>(null)
  const [graphStale, setGraphStale] = useState(false)
  const [graphStaleMessage, setGraphStaleMessage] = useState<string | null>(null)
  const [draftsByPath, setDraftsByPath] = useState<Record<string, DraftEntry>>({})
  const [draftRestore, setDraftRestore] = useState<{ path: string; draft: DraftEntry } | null>(null)
  const [pendingClosePath, setPendingClosePath] = useState<string | null>(null)
  const [pendingClosePaths, setPendingClosePaths] = useState<string[]>([])
  const [pendingActivePath, setPendingActivePath] = useState<string | null>(null)
  const [pendingReloadPath, setPendingReloadPath] = useState<string | null>(null)
  const [pendingJump, setPendingJump] = useState<PendingFileJump | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [confirmReason, setConfirmReason] = useState<string | null>(null)
  const [pendingView, setPendingView] = useState<WorkspaceView | null>(null)
  const DRAFT_MAX_CHARS = 120_000

  const hasDirtyEditors = useMemo(() => {
    return Object.values(fileEditorsByPath).some((entry) => isEntryDirty(entry))
  }, [fileEditorsByPath])

  useEffect(() => {
    if (!hasDirtyEditors) return
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
    }
  }, [hasDirtyEditors])

  useEffect(() => {
    if (!activeProject || !activeFilePath) {
      setFileDependencies(null)
      setFileDependenciesMeta(null)
      setFileDependenciesBusy(false)
      return
    }
    let active = true
    setFileDependenciesBusy(true)
    getFileDependencies(activeProject.id, activeFilePath, { limit: 2000 })
      .then((res) => {
        if (!active) return
        setFileDependencies({ in: res.inbound || [], out: res.outbound || [] })
        setFileDependenciesMeta({
          total_in: res.meta?.total_inbound ?? res.inbound?.length ?? 0,
          total_out: res.meta?.total_outbound ?? res.outbound?.length ?? 0,
          truncated_in: Boolean(res.meta?.truncated_inbound),
          truncated_out: Boolean(res.meta?.truncated_outbound),
          next_cursor_in: res.meta?.next_cursor_in ?? null,
          next_cursor_out: res.meta?.next_cursor_out ?? null,
          cursor_in: res.meta?.cursor_in ?? null,
          cursor_out: res.meta?.cursor_out ?? null,
        })
      })
      .catch(() => {
        if (!active) return
        setFileDependencies({ in: [], out: [] })
        setFileDependenciesMeta({
          total_in: 0,
          total_out: 0,
          truncated_in: false,
          truncated_out: false,
          next_cursor_in: null,
          next_cursor_out: null,
          cursor_in: null,
          cursor_out: null,
        })
      })
      .finally(() => {
        if (active) setFileDependenciesBusy(false)
      })
    return () => {
      active = false
    }
  }, [activeFilePath, activeProject])

  const loadMoreDependencies = useCallback(async () => {
    if (!activeProject || !activeFilePath || !fileDependenciesMeta) return
    if (!fileDependenciesMeta.next_cursor_in && !fileDependenciesMeta.next_cursor_out) return
    setFileDependenciesBusy(true)
    try {
      const res = await getFileDependencies(activeProject.id, activeFilePath, {
        limit: 2000,
        cursorIn: fileDependenciesMeta.next_cursor_in ?? undefined,
        cursorOut: fileDependenciesMeta.next_cursor_out ?? undefined,
      })
      setFileDependencies((prev) => {
        const prevIn = prev?.in ?? []
        const prevOut = prev?.out ?? []
        const nextIn = [...prevIn, ...(res.inbound || [])]
        const nextOut = [...prevOut, ...(res.outbound || [])]
        return {
          in: Array.from(new Set(nextIn)),
          out: Array.from(new Set(nextOut)),
        }
      })
      setFileDependenciesMeta({
        total_in: res.meta?.total_inbound ?? fileDependenciesMeta.total_in,
        total_out: res.meta?.total_outbound ?? fileDependenciesMeta.total_out,
        truncated_in: Boolean(res.meta?.truncated_inbound),
        truncated_out: Boolean(res.meta?.truncated_outbound),
        next_cursor_in: res.meta?.next_cursor_in ?? null,
        next_cursor_out: res.meta?.next_cursor_out ?? null,
        cursor_in: res.meta?.cursor_in ?? fileDependenciesMeta.cursor_in ?? null,
        cursor_out: res.meta?.cursor_out ?? fileDependenciesMeta.cursor_out ?? null,
      })
    } catch {
      // keep existing state on failure
    } finally {
      setFileDependenciesBusy(false)
    }
  }, [activeFilePath, activeProject, fileDependenciesMeta])

  const buildWorkspaceState = useCallback((): WorkspaceStateV3 => {
    const fileEditorState: Record<string, { dirty?: boolean }> = {}
    for (const path of openFilePaths || []) {
      const entry = fileEditorsByPath[path]
      fileEditorState[path] = { dirty: entry ? entry.dirty : false }
    }
    return {
      version: 3,
      selectedPath,
      pinnedPaths: (pinnedPaths || []).slice(0, PIN_LIMIT),
      selectionTrail: (selectionTrail || []).slice(-3),
      backStack: (backStack || []).slice(-200),
      forwardStack: (forwardStack || []).slice(-200),
      graphMode,
      graphLimitN,
      graphHops,
      graphLocalMax,
      workspaceView,
      openFilePaths: (openFilePaths || []).slice(0, 200),
      activeFilePath,
      fileEditorsByPath: fileEditorState,
    }
  }, [
    selectedPath,
    pinnedPaths,
    selectionTrail,
    backStack,
    forwardStack,
    graphMode,
    graphLimitN,
    graphHops,
    graphLocalMax,
    workspaceView,
    openFilePaths,
    activeFilePath,
    fileEditorsByPath,
  ])

  const persistWorkspace = useCallback(
    (projectId: number) => {
      if (!Number.isFinite(projectId) || projectId <= 0) return
      try {
        safeStorageSet(wsKey(projectId), JSON.stringify(buildWorkspaceState()))
      } catch {}
    },
    [buildWorkspaceState],
  )

  const {
    searchQuery, setSearchQuery, searchResults, setSearchResults,
    searchSemanticResults, setSearchSemanticResults, searchBusy,
    semanticSearchEnabled, setSemanticSearchEnabled, semanticSearchFallbackUsed,
    semanticSearchUnavailableReason, textSearchQuery, setTextSearchQuery,
    textSearchResults, textSearchMeta, textSearchBusy, textSearchCaseSensitive,
    setTextSearchCaseSensitive, textSearchPrefix, setTextSearchPrefix,
    textSearchError, onSearchNodes, onSearchText,
  } = useGraphSearch({ activeProject, notifyInfo, setErrorMessage })


  useEffect(() => {
    if (!orgSelectionStorageFailureMarker) return
    notifyInfo('Organization selection is active for this session only and will not be saved after reload.')
  }, [orgSelectionStorageFailureMarker, notifyInfo])

  useEffect(() => {
    return addStorageErrorListener(() => {
      notifyInfo('Local storage unavailable — preferences will not be saved.')
    })
  }, [notifyInfo])

  const trackTaskStatus = useCallback((task: TaskStatus, kind: TaskBannerItem['kind'], label: string) => {
    setTaskStatuses((prev) => {
      const existing = prev.find((item) => item.id === task.task_id)
      if (existing) {
        return prev.map((item) =>
          item.id === task.task_id
            ? { ...item, status: task.status, error: task.error ? String(task.error) : item.error }
            : item
        )
      }
      const next: TaskBannerItem = {
        id: task.task_id,
        kind,
        status: task.status,
        label,
        startedAt: Date.now(),
        finishedAt: null,
        error: task.error ? String(task.error) : null,
      }
      return [...prev, next].slice(-5)
    })
  }, [])

  const refreshTaskStatuses = useCallback(async () => {
    const pending = taskStatusesRef.current.filter((item) => item.status === 'pending' || item.status === 'running')
    if (!pending.length) return
    const updates = await Promise.all(
      pending.map(async (item) => {
        try {
          const status = await getTaskStatus(item.id)
          return { item, status }
        } catch {
          return { item, status: null }
        }
      })
    )
    setTaskStatuses((prev) =>
      prev.map((item) => {
        const update = updates.find((u) => u.item.id === item.id)
        if (!update || !update.status) return item
        const finishedAt =
          update.status.status === 'succeeded' || update.status.status === 'failed'
            ? Date.now()
            : item.finishedAt
        return {
          ...item,
          status: update.status.status,
          error: update.status.error ? String(update.status.error) : item.error,
          finishedAt,
        }
      })
    )
  }, [])

  useEffect(() => {
    if (!taskStatuses.length) return
    const interval = window.setInterval(() => {
      void refreshTaskStatuses()
    }, 3000)
    return () => window.clearInterval(interval)
  }, [refreshTaskStatuses, taskStatuses.length])

  const clearFinishedTasks = useCallback(() => {
    setTaskStatuses((prev) => prev.filter((item) => item.status === 'pending' || item.status === 'running'))
  }, [])

  const dismissTaskStatus = useCallback((taskId: string) => {
    setTaskStatuses((prev) => prev.filter((item) => item.id !== taskId))
  }, [])

  const resetForSelectionChange = useCallback(() => {
    nodeSeqRef.current++
    setNodeInfo(null); setContract(null); setRunResult(null); setFullPatch(null); setErrorMessage(null)
  }, [setErrorMessage])

  useEffect(() => {
    const pid = Number(activeProject?.id)
    if (!Number.isFinite(pid) || pid <= 0) {
      workspaceBootingRef.current = false
      return
    }
    workspaceBootingRef.current = true
    restoredEditorRef.current = false

    const raw = safeStorageGet(wsKey(pid))
    const legacyRaw = raw ? null : safeStorageGet(legacyWsKey(pid))
    const legacyRawV1 = raw || legacyRaw ? null : safeStorageGet(legacyWsKeyV1(pid))
    const parsed =
      raw
        ? safeStorageGetJson<Partial<WorkspaceStateV3>>(wsKey(pid), {})
        : legacyRaw
          ? safeStorageGetJson<Partial<WorkspaceStateV2>>(legacyWsKey(pid), {})
          : legacyRawV1
            ? safeStorageGetJson<Partial<WorkspaceStateV1>>(legacyWsKeyV1(pid), {})
            : null
    if (parsed) {
      const nextSelected = asStr(parsed.selectedPath) || null
      const nextPinned = asStrArr(parsed.pinnedPaths, 20).slice(0, PIN_LIMIT)
      const nextTrail = asStrArr(parsed.selectionTrail, 20).slice(-3)
      const nextBack = asStrArr(parsed.backStack, 300).slice(-200)
      const nextFwd = asStrArr(parsed.forwardStack, 300).slice(-200)
      const nextWorkspaceView =
        'workspaceView' in parsed && (parsed.workspaceView === 'editor' || parsed.workspaceView === 'graph')
          ? parsed.workspaceView
          : 'graph'
      const nextOpenFilePaths = 'openFilePaths' in parsed ? asStrArr(parsed.openFilePaths, 200) : []
      const nextActiveFilePath =
        'activeFilePath' in parsed && parsed.activeFilePath && nextOpenFilePaths.includes(parsed.activeFilePath)
          ? parsed.activeFilePath
          : null
      const nextFileEditors: Record<string, FileEditorEntry> = {}
      for (const path of nextOpenFilePaths) {
        nextFileEditors[path] = createFileEditorEntry(path)
      }

      setGraphMode(asGraphMode(parsed.graphMode, 'limit'))
      setGraphLimitN(asInt(parsed.graphLimitN, 2000, 100, 20000))
      setGraphHops(asInt(parsed.graphHops, 2, 1, 6))
      setGraphLocalMax(asInt(parsed.graphLocalMax, 400, 50, 2000))

      setPinnedPaths(nextPinned)
      setSelectionTrail(nextTrail)
      setBackStack(nextBack)
      setForwardStack(nextFwd)
      setSelectedPath(nextSelected)
      setWorkspaceViewState(nextWorkspaceView)
      setOpenFilePaths(nextOpenFilePaths)
      setActiveFilePath(nextActiveFilePath)
      setFileEditorsByPath(nextFileEditors)
      restoredEditorRef.current = Boolean(nextActiveFilePath)
      selectedPathRef.current = nextSelected; selectionTrailRef.current = nextTrail; backStackRef.current = nextBack; forwardStackRef.current = nextFwd
    }

    resetForSelectionChange()
    setPrompt('')
    setSearchQuery('')
    setSearchResults([])
    setErrorMessage(null)
    setFileSaveBanner(null)
    setGraphStale(false)
    setGraphStaleMessage(null)

    const t = window.setTimeout(() => {
      workspaceBootingRef.current = false
    }, 0)
    return () => window.clearTimeout(t)
  }, [activeProject?.id, resetForSelectionChange, setErrorMessage])

  useEffect(() => {
    const pid = Number(activeProject?.id)
    if (!Number.isFinite(pid) || pid <= 0) {
      setDraftsByPath({})
      setDraftRestore(null)
      draftPromptedRef.current = new Set()
      return
    }
    const raw = safeStorageGetJson<Record<string, DraftEntry>>(draftKey(pid), {})
    const next: Record<string, DraftEntry> = {}
    for (const [path, draft] of Object.entries(raw || {})) {
      if (!path || !draft || typeof draft.content !== 'string') continue
      const original = typeof draft.original === 'string' ? draft.original : ''
      const updatedAt = Number(draft.updatedAt || 0)
      next[path] = { content: draft.content, original, updatedAt: Number.isFinite(updatedAt) ? updatedAt : 0 }
    }
    setDraftsByPath(next)
    setDraftRestore(null)
    draftPromptedRef.current = new Set()
  }, [activeProject?.id])

  // Persist workspace (debounced) when state changes
  useEffect(() => {
    const pid = Number(activeProject?.id)
    if (!Number.isFinite(pid) || pid <= 0) return
    if (workspaceBootingRef.current) return

    if (workspaceSaveTimerRef.current != null) window.clearTimeout(workspaceSaveTimerRef.current)
    workspaceSaveTimerRef.current = window.setTimeout(() => {
      workspaceSaveTimerRef.current = null
      persistWorkspace(pid)
    }, 150)

    return () => {
      if (workspaceSaveTimerRef.current != null) window.clearTimeout(workspaceSaveTimerRef.current)
    }
  }, [
    activeProject?.id,
    selectedPath,
    pinnedPaths,
    selectionTrail,
    backStack,
    forwardStack,
    graphMode,
    graphLimitN,
    graphHops,
    graphLocalMax,
    workspaceView,
    openFilePaths,
    activeFilePath,
    fileEditorsByPath,
    persistWorkspace,
  ])

  useEffect(() => {
    const pid = Number(activeProject?.id)
    if (!Number.isFinite(pid) || pid <= 0) return
    if (workspaceBootingRef.current) return

    if (draftSaveTimerRef.current != null) window.clearTimeout(draftSaveTimerRef.current)
    draftSaveTimerRef.current = window.setTimeout(() => {
      draftSaveTimerRef.current = null
      const next: Record<string, DraftEntry> = { ...draftsByPath }
      let changed = false
      Object.entries(fileEditorsByPath).forEach(([path, entry]) => {
        if (!path) return
        if (entry?.dirty && entry.content.length <= DRAFT_MAX_CHARS) {
          const prev = next[path]
          if (!prev || prev.content !== entry.content || prev.original !== entry.original) {
            next[path] = { content: entry.content, original: entry.original, updatedAt: Date.now() }
            changed = true
          }
          return
        }
        if (next[path]) {
          delete next[path]
          changed = true
        }
      })
      if (!changed) return
      setDraftsByPath(next)
      try {
        if (Object.keys(next).length > 0) {
          safeStorageSet(draftKey(pid), JSON.stringify(next))
        } else {
          safeStorageRemove(draftKey(pid))
        }
      } catch {}
    }, 200)

    return () => {
      if (draftSaveTimerRef.current != null) window.clearTimeout(draftSaveTimerRef.current)
    }
  }, [DRAFT_MAX_CHARS, activeProject?.id, draftsByPath, fileEditorsByPath])

  const setSelection = useCallback(
    (nextRaw: string | null, opts: { pushHistory?: boolean } = {}) => {
      const pushHistory = opts.pushHistory ?? true
      const nextStr = typeof nextRaw === 'string' ? nextRaw.trim() : ''
      const next = nextStr ? nextStr : null
      const current = selectedPathRef.current

      if (current === next) return

      if (next) {
        const prev = selectionTrailRef.current || []
        const filtered = prev.filter((p) => p !== next)
        const out = [...filtered, next]
        const trail = out.slice(-3)
        selectionTrailRef.current = trail
        setSelectionTrail(trail)
      }

      if (pushHistory) {
        if (current) {
          const b = [...(backStackRef.current || []), current].slice(-200)
          backStackRef.current = b
          setBackStack(b)
        }
        forwardStackRef.current = []
        setForwardStack([])
      }

      selectedPathRef.current = next
      setSelectedPath(next)

      nodeSeqRef.current++
      resetForSelectionChange()
    },
    [resetForSelectionChange],
  )

  const {
    onClearSelection, isSelectedPinned, togglePinPath, togglePinSelected,
    unpinPath, clearPins, canGoBack, canGoForward, goBack, goForward,
    onGraphBackgroundTap,
  } = useSelectionNav({
    selectedPath, pinnedPaths, backStack, forwardStack, PIN_LIMIT,
    selectedPathRef, backStackRef, forwardStackRef, selectionTrailRef,
    setSelectedPath, setPinnedPaths, setBackStack, setForwardStack, setSelectionTrail,
    setSelection, resetForSelectionChange,
  })

  const projectsQuery = useQuery<Project[]>({
    queryKey: ['projects', selectedOrgId],
    enabled: selectedOrgId !== null,
    queryFn: listProjects,
    initialData: [],
  })

  const runsQuery = useQuery<RunRecord[]>({
    queryKey: ['runs', selectedOrgId, activeProject?.id],
    enabled: selectedOrgId !== null && !!activeProject,
    queryFn: async () => {
      if (!activeProject) return [] as RunRecord[]
      return listRuns(activeProject.id)
    },
    initialData: [],
  })

  const graphQueryKey = useMemo(
    () => {
      const pid = activeProject?.id ?? null
      if (!pid) return ['graph', selectedOrgId, null]
      if (graphMode === 'local') return ['graph', selectedOrgId, pid, 'local', selectedPath ?? null, graphHops, graphLocalMax]
      if (graphMode === 'limit') return ['graph', selectedOrgId, pid, 'limit', graphLimitN]
      if (graphMode === 'full') return ['graph', selectedOrgId, pid, 'full']
      return ['graph', selectedOrgId, pid, graphMode]
    },
    [activeProject?.id, graphMode, graphHops, graphLocalMax, graphLimitN, selectedOrgId, selectedPath],
  )

  const graphQuery = useQuery<GraphData | null>({
    queryKey: graphQueryKey,
    enabled: selectedOrgId !== null && !!activeProject && (graphMode !== 'local' || !!selectedPath),
    queryFn: async (): Promise<GraphData | null> => {
      if (!activeProject) return null
      const projectId = activeProject.id
      if (graphMode === 'local') {
        if (!selectedPath) throw new Error('Select a file to build a local graph.')
        return getLocalGraph(projectId, selectedPath, graphHops, graphLocalMax, graphLocalMax * 2)
      }
      if (graphMode === 'full') return getGraph(projectId, 0)
      if (graphMode === 'limit') return getGraph(projectId, graphLimitN)
      return getGraph(projectId, undefined)
    },
    staleTime: 15_000,
  })

  const nodeQuery = useQuery<{ info: NodeInfo | null; contract: NodeContract | null }>({
    queryKey: ['node', selectedOrgId, activeProject?.id, selectedPath],
    enabled: selectedOrgId !== null && !!activeProject && !!selectedPath,
    queryFn: async () => {
      if (!activeProject || !selectedPath) return { info: null, contract: null }
      const seq = ++nodeSeqRef.current
      const [niRes, ctRes] = await Promise.allSettled([
        getNode(activeProject.id, selectedPath),
        getContract(activeProject.id, selectedPath),
      ])

      if (nodeSeqRef.current !== seq) return { info: null, contract: null }

      let err: string | null = null
      const info = niRes.status === 'fulfilled' ? niRes.value : null
      if (niRes.status !== 'fulfilled') err = extractError(niRes.reason)

      const contractRes = ctRes.status === 'fulfilled' ? ctRes.value : null
      if (ctRes.status !== 'fulfilled') {
        const e2 = extractError(ctRes.reason)
        const shouldIgnoreContractError = Boolean(info?.indexing_started && info?.node_available === false)
        if (!shouldIgnoreContractError) {
          err = err ? `${err}\n${e2}` : e2
        }
      }

      if (info?.indexing_started && info?.node_available === false) {
        setErrorMessage(info.message || 'Индексация запущена, узел временно недоступен')
      } else if (err) {
        setErrorMessage(err)
      }
      return { info, contract: contractRes }
    },
  })

  useEffect(() => {
    const queryError =
      (projectsQuery.error as Error | null) ||
      (graphQuery.error as Error | null) ||
      (nodeQuery.error as Error | null) ||
      (runsQuery.error as Error | null)

    if (queryError) setErrorMessage(extractError(queryError))
  }, [graphQuery.error, nodeQuery.error, projectsQuery.error, runsQuery.error])

  useEffect(() => {
    if (nodeQuery.data) {
      setNodeInfo(nodeQuery.data.info)
      setContract(nodeQuery.data.contract)
    }
  }, [nodeQuery.data])

  const selectProjectLocal = useCallback((p: Project) => {
    if (activeProject?.id) persistWorkspace(activeProject.id)
    workspaceBootingRef.current = true
    setActiveProject(p)
    setErrorMessage(null)

    nodeSeqRef.current++

    selectedPathRef.current = null
    backStackRef.current = []
    forwardStackRef.current = []
    selectionTrailRef.current = []
    setSelectedPath(null)
    setNodeInfo(null)
    setContract(null)
    setRunResult(null)
    setFullPatch(null)
    setGraphMode('limit')
    setGraphLimitN(2000)
    setGraphHops(2)
    setGraphLocalMax(400)
    setWorkspaceViewState('graph')
    setPrompt('')
    setSearchQuery('')
    setSearchResults([])
    setBackStack([])
    setForwardStack([])
    setSelectionTrail([])
    setPinnedPaths([])
    setOpenFilePaths([])
    setFileEditorsByPath({})
    setActiveFilePath(null)
    setPendingClosePath(null)
    setPendingClosePaths([])
    setPendingActivePath(null)
    setPendingReloadPath(null)
    setConfirmOpen(false)
    setConfirmReason(null)
    setPendingView(null)
  }, [activeProject?.id, persistWorkspace])

  const clearActiveProject = useCallback(() => {
    if (activeProject?.id) persistWorkspace(activeProject.id)
    workspaceBootingRef.current = true
    setActiveProject(null)
    setErrorMessage(null)
    nodeSeqRef.current++
    selectedPathRef.current = null
    backStackRef.current = []
    forwardStackRef.current = []
    selectionTrailRef.current = []
    setSelectedPath(null)
    setNodeInfo(null)
    setContract(null)
    setRunResult(null)
    setFullPatch(null)
    setPrompt('')
    setSearchQuery('')
    setSearchResults([])
    setBackStack([])
    setForwardStack([])
    setSelectionTrail([])
    setPinnedPaths([])
    setWorkspaceViewState('graph')
    setOpenFilePaths([])
    setFileEditorsByPath({})
    setActiveFilePath(null)
    setPendingClosePath(null)
    setPendingClosePaths([])
    setPendingActivePath(null)
    setPendingReloadPath(null)
    setConfirmOpen(false)
    setConfirmReason(null)
    setPendingView(null)
  }, [activeProject?.id, persistWorkspace, setErrorMessage])

  const onSelectOrg = useCallback((orgId: number | null) => {
    if (orgId == null) {
      applyOrgSelection(null)
      return
    }
    const match = orgs.find((org) => org.id === orgId)
    applyOrgSelection(match ? match.id : null)
  }, [applyOrgSelection, orgs])

  useEffect(() => {
    if (prevOrgIdRef.current === selectedOrgId) return
    prevOrgIdRef.current = selectedOrgId

    clearActiveProject()
    queryClient.invalidateQueries({ queryKey: ['projects', selectedOrgId] })
    queryClient.invalidateQueries({ queryKey: ['runs'] })
    queryClient.invalidateQueries({ queryKey: ['graph'] })
    queryClient.invalidateQueries({ queryKey: ['node'] })
    queryClient.invalidateQueries({ queryKey: ['files'] })
  }, [clearActiveProject, queryClient, selectedOrgId])

  const projects = projectsQuery.data ?? []
  const runs = runsQuery.data ?? []
  const graph = graphQuery.data ?? null

  const [fileMetaByPath, setFileMetaByPath] = useState<Record<string, ProjectFileItem>>({})

  const registerFileMeta = useCallback((entries: ProjectTreeEntry[]) => {
    setFileMetaByPath((prev) => {
      let changed = false
      const next = { ...prev }
      for (const entry of entries) {
        if (entry.type !== 'file' || !entry.file) continue
        if (next[entry.file.path] === entry.file) continue
        next[entry.file.path] = entry.file
        changed = true
      }
      return changed ? next : prev
    })
  }, [])

  const [docs, setDocs] = useState<ProjectDocs | null>(null)
  const [docsBusy, setDocsBusy] = useState(false)
  const [docsBuildBusy, setDocsBuildBusy] = useState(false)
  const [docsBuildError, setDocsBuildError] = useState<string | null>(null)

  useEffect(() => {
    setDocs(null)
    setDocsBuildError(null)
  }, [activeProject?.id])

  useEffect(() => {
    setFileMetaByPath({})
  }, [activeProject?.id])

  useEffect(() => {
    setOpenFilePaths([])
    setFileEditorsByPath({})
    setActiveFilePath(null)
    setPendingClosePath(null)
    setPendingClosePaths([])
    setPendingActivePath(null)
    setPendingReloadPath(null)
    setConfirmOpen(false)
    setConfirmReason(null)
    setPendingView(null)
  }, [activeProject?.id])

  const loadDocs = useCallback(async () => {
    if (!activeProject) return
    setDocsBusy(true)
    setDocsBuildError(null)
    setErrorMessage(null)
    try {
      const d = await getProjectDocs(activeProject.id)
      setDocs(d)
    } catch (e: any) {
      const info = getAppErrorInfo(e)
      const message = info?.message?.toLowerCase() ?? ''
      const isDocsMissing =
        info?.code === 'not_found' &&
        ((message.includes('документац') && message.includes('не найден')) ||
          (message.includes('docs') && (message.includes('not found') || message.includes('missing'))))
      if (isDocsMissing) {
        setDocs(null)
        return
      }
      setDocs(null)
      setErrorMessage(extractError(e))
    } finally {
      setDocsBusy(false)
    }
  }, [activeProject, setErrorMessage])

  const buildDocs = useCallback(async () => {
    if (!activeProject) return
    setDocsBuildBusy(true)
    setDocsBuildError(null)
    setErrorMessage(null)
    try {
      const initial = await buildProjectDocsStatus(activeProject.id)
      if (isTaskStatus(initial)) {
        trackTaskStatus(initial, 'docs', `Docs ${activeProject.name}`)
      }
      const d = await waitForTaskResult<ProjectDocs>(initial, { pollIntervalMs: 1200, maxAttempts: 300 })
      setDocs(d)
      setDocsBuildError(null)
      notifyInfo('Docs built')
    } catch (e: any) {
      setDocsBuildError(extractError(e))
      setErrorMessage(extractError(e))
    } finally {
      setDocsBuildBusy(false)
    }
  }, [activeProject, notifyInfo, setErrorMessage, trackTaskStatus])

  const {
    updateFileEditorEntry, setActiveFileContent, loadFileEditor, clearConfirm,
    openFileEditor, openFileEditorAt, persistDrafts, restoreDraft, discardDraft,
    clearDrafts, clearPendingJump, requestReloadFileEditor, queueMutationIndexingPoll,
    saveFileEditorPath, saveFileEditor, saveAllOpenFiles, closeFileEditorPaths,
    confirmSave, confirmDiscard, confirmCancel,
  } = useFileEditors({
    activeProject, selectedOrgId, notifyInfo, queryClient, draftPromptedRef,
    activeFilePath, openFilePaths, fileEditorsByPath, draftsByPath, draftRestore,
    confirmReason, pendingClosePath, pendingClosePaths, pendingActivePath,
    pendingReloadPath, pendingView, workspaceView,
    setActiveFilePath, setOpenFilePaths, setFileEditorsByPath, setDraftsByPath,
    setDraftRestore, setFileSaveBanner, setGraphStale, setGraphStaleMessage,
    setConfirmOpen, setConfirmReason, setPendingClosePath, setPendingClosePaths,
    setPendingActivePath, setPendingReloadPath, setPendingJump, setPendingView,
    setWorkspaceViewState,
  })

  const runOp = useCallback(async (fn: () => Promise<void>) => {
    setBusyCount((count) => count + 1)
    setErrorMessage(null)
    try {
      await fn()
    } catch (e: any) {
      setErrorMessage(extractError(e))
    } finally {
      setBusyCount((count) => Math.max(0, count - 1))
    }
  }, [])

  const runOpThrow = useCallback(async (fn: () => Promise<void>) => {
    setBusyCount((count) => count + 1)
    setErrorMessage(null)
    try {
      await fn()
    } catch (e: any) {
      setErrorMessage(extractError(e))
      throw e
    } finally {
      setBusyCount((count) => Math.max(0, count - 1))
    }
  }, [setErrorMessage])

  const {
    onPickProject, onCreateProject, onDeleteActiveProject, onScan, onRefresh,
    onCreateFile, onRenameFile, onDeleteFile,
  } = useProjectActions({
    activeProject, allowLocalRootPath, newName, newArchive, newPath, selectedOrgId,
    selectedPathRef, projectsQuery, queryClient, runOp, runOpThrow, selectProjectLocal,
    clearActiveProject, trackTaskStatus, queueMutationIndexingPoll, setSelection,
    setNewArchive, setNewPath, setPinnedPaths, setActiveFilePath, setOpenFilePaths,
    setFileEditorsByPath, setFileSaveBanner, setGraphStale, setGraphStaleMessage,
  })

  const {
    onDeleteRun, onLoadFullGraph, onNavigatePath, onSelectNodePath, onGraphNodeTap,
    onLoadFullPatch, onApplyRunPatch, onLoadRun, onRun, onQuickSummary,
    onRunWithExpandedContext,
  } = useGraphRunActions({
    config,
    activeProject, applyPatch, contract, graph, graphMode, nodeInfo, notifyInfo, prompt,
    queryClient, runOp, runResult, selectedOrgId, selectedPath,
    setErrorMessage, setFullPatch, setGraphMode, setGraphStale, setGraphStaleMessage,
    setPatchBusy, setRightPanelOpen, setRunLoadBusy, setRunResult, setSelection, trackTaskStatus,
  })

  const {
    closeFileEditor, closeAllTabs, closeOtherTabs, closeTabsToRight,
    setWorkspaceView, toggleWorkspaceView,
    requestFindInFile, requestReplaceInFile, requestOutlineInFile,
  } = useFileTabs({
    activeFilePath, openFilePaths, fileEditorsByPath, workspaceView, selectedPathRef,
    closeFileEditorPaths, openFileEditor, setSelection,
    setConfirmOpen, setConfirmReason, setPendingClosePath, setPendingClosePaths,
    setPendingActivePath, setPendingView, setWorkspaceViewState,
    setFindRequestId, setReplaceRequestId, setOutlineRequestId,
  })

  const fileEditorOpen = workspaceView === 'editor'

  const { registerUndoRedoHandlers } = useGlobalKeyboard({
    canGoBack, canGoForward, goBack, goForward,
    paletteOpen, setPaletteOpen, focusGraph, setFocusGraph,
    selectedPath, onClearSelection, onFocusSearch,
    workspaceView, toggleWorkspaceView, graph,
    leftPanelOpen, rightPanelOpen, setLeftPanelOpen, setRightPanelOpen,
    toggleLeftPanel, toggleRightPanel, toggleCompactMode,
    fileEditorOpen, activeFilePath, openFilePaths, openFileEditor,
    requestFindInFile, requestReplaceInFile, requestOutlineInFile,
    setGotoLineRequestId,
  })

  useEffect(() => {
    if (workspaceView !== 'editor') return
    if (activeFilePath && restoredEditorRef.current) {
      restoredEditorRef.current = false
      void loadFileEditor(activeFilePath)
      return
    }
    if (!selectedPath) return
    if (selectedPath === activeFilePath) return
    void openFileEditor(selectedPath)
  }, [activeFilePath, loadFileEditor, openFileEditor, selectedPath, workspaceView])

  useEffect(() => {
    const prevActiveFilePath = prevActiveFilePathRef.current
    prevActiveFilePathRef.current = activeFilePath
    if (workspaceView !== 'editor') return
    if (!activeFilePath) return
    if (prevActiveFilePath === activeFilePath) return
    if (selectedPath === activeFilePath) return
    setSelection(activeFilePath, { pushHistory: false })
  }, [activeFilePath, selectedPath, setSelection, workspaceView])

  const selectedInGraph = useMemo(() => {
    if (!selectedPath || !graph?.nodes?.length) return false
    return graph.nodes.some((n: GraphNode) => n.path === selectedPath || n.id === selectedPath)
  }, [graph, selectedPath])

  const activeFileEntry = useMemo(() => {
    if (!activeFilePath) return null
    return fileEditorsByPath[activeFilePath] ?? null
  }, [activeFilePath, fileEditorsByPath])

  const graphBusy = graphQuery.isFetching
  const nodeBusy = nodeQuery.isFetching
  const mutationBusy = busy || projectsQuery.isFetching
  const fileEditorDirty = activeFileEntry ? activeFileEntry.content !== activeFileEntry.original : false
  const fileEditorPath = activeFilePath
  const fileEditorContent = activeFileEntry?.content ?? ''
  const fileEditorOriginal = activeFileEntry?.original ?? ''
  const fileEditorTruncated = activeFileEntry?.truncated ?? false
  const fileEditorBusy = activeFileEntry?.busy ?? false
  const fileEditorSaving = activeFileEntry?.saving ?? false
  const fileEditorError = activeFileEntry?.error ?? null
  const draftCount = useMemo(() => Object.keys(draftsByPath).length, [draftsByPath])

  const canRun = useMemo(() => {
    const fileReady = !!selectedPath && (contract != null || nodeInfo != null)
    return (
      !!activeProject &&
      !!selectedPath &&
      fileReady &&
      !!prompt.trim() &&
      !mutationBusy &&
      !nodeBusy
    )
  }, [activeProject, selectedPath, contract, nodeInfo, prompt, mutationBusy, nodeBusy])

  return {
    // state
    orgs,
    orgsLoading: orgsQuery.isFetching,
    selectedOrgId,
    projects,
    projectsLoading: projectsQuery.isFetching,
    activeProject,
    graph,
    fileMetaByPath,
    registerFileMeta,
    fileDependencies,
    fileDependenciesMeta,
    fileDependenciesBusy,
    loadMoreDependencies,
    fileSaveBanner,
    graphStale,
    graphStaleMessage,
    draftRestore,
    restoreDraft,
    discardDraft,
    clearDrafts,
    allowLocalRootPath,
    docs,
    docsBusy,
    docsBuildBusy,
    docsBuildError,
    loadDocs,
    buildDocs,
    fileEditorOpen,
    fileEditorPath,
    fileEditorContent,
    fileEditorOriginal,
    fileEditorDirty,
    fileEditorTruncated,
    fileEditorBusy,
    fileEditorSaving,
    fileEditorError,
    draftCount,
    openFilePaths,
    fileEditorsByPath,
    activeFilePath,
    gotoLineRequestId,
    findRequestId,
    replaceRequestId,
    outlineRequestId,
    setFileEditorContent: setActiveFileContent,
    confirmOpen,
    confirmReason,
    confirmSave,
    confirmDiscard,
    confirmCancel,
    openFileEditor,
    openFileEditorAt,
    closeFileEditor,
    requestFindInFile,
    requestReplaceInFile,
    requestOutlineInFile,
    requestReloadFileEditor,
    saveFileEditor,
    saveAllOpenFiles,
    pendingJump,
    clearPendingJump,
    runs,
    newName,
    newArchive,
    newPath,
    selectedPath,
    selectedInGraph,
    nodeInfo,
    contract,
    mode,
    depth,
    depMode,
    retrievalMode,
    agenticMaxCalls,
    agenticMaxFileChars,
    agenticMaxTotalToolOutputChars,
    agenticTemperature,
    agenticEvidenceMode,
    packMaxFiles,
    packMaxCharsPerFile,
    packMaxTotalChars,
    applyPatch,
    prompt,
    runResult,
    fullPatch,
    busy: mutationBusy,
    graphBusy,
    nodeBusy,
    patchBusy,
    runLoadBusy,
    error,
    graphMode,
    graphLimitN,

    // setters (UI)
    setNewName,
    setNewArchive,
    setNewPath,
    setGraphMode,
    setGraphLimitN,
    graphHops,
    setGraphHops,
    graphLocalMax,
    setGraphLocalMax,
    onSelectOrg,

    searchQuery,
    setSearchQuery,
    searchResults,
    searchSemanticResults,
    semanticSearchFallbackUsed,
    semanticSearchEnabled,
    setSemanticSearchEnabled,
    semanticSearchUnavailableReason,
    searchBusy,
    onSearchNodes,
    textSearchQuery,
    setTextSearchQuery,
    textSearchResults,
    textSearchMeta,
    textSearchBusy,
    textSearchCaseSensitive,
    setTextSearchCaseSensitive,
    textSearchPrefix,
    setTextSearchPrefix,
    textSearchError,
    onSearchText,
    setMode,
    setDepth,
    setDepMode,
    setRetrievalMode,
    setAgenticMaxCalls,
    setAgenticMaxFileChars,
    setAgenticMaxTotalToolOutputChars,
    setAgenticTemperature,
    setAgenticEvidenceMode,
    setPackMaxFiles,
    setPackMaxCharsPerFile,
    setPackMaxTotalChars,
    setApplyPatch,
    setPrompt,

    notifications,
    dismissNotification,
    notifyInfo,
    notifyError,
    taskStatuses,
    refreshTaskStatuses,
    clearFinishedTasks,
    dismissTaskStatus,
    focusGraph,
    setFocusGraph,
    compactMode,
    setCompactMode,
    toggleCompactMode,
    workspaceView,
    setWorkspaceView,
    toggleWorkspaceView,
    leftPanelOpen,
    rightPanelOpen,
    setLeftPanelOpen,
    setRightPanelOpen,
    toggleLeftPanel,
    toggleRightPanel,
    paletteOpen,
    setPaletteOpen,
    registerUndoRedoHandlers,

    selectionTrail,
    onNavigatePath,

    pinnedPaths,
    isSelectedPinned,
    togglePinSelected,
    togglePinPath,
    unpinPath,
    clearPins,
    
    // actions
    onPickProject,
    onCreateProject,
    onDeleteActiveProject,
    onScan,
    onRefresh,
    onLoadFullGraph,
    onClearSelection,
    canGoBack,
    canGoForward,
    goBack,
    goForward,
    onGraphBackgroundTap,
    onSelectNodePath,
    onGraphNodeTap,
    onRun,
    onRunWithExpandedContext,
    onQuickSummary,
    onDeleteRun,
    onLoadFullPatch,
    onApplyRunPatch,
    onLoadRun,
    onCreateFile,
    onRenameFile,
    onDeleteFile,
    closeAllTabs,
    closeOtherTabs,
    closeTabsToRight,

    // derived
    canRun,
  }
}
