// frontend/src/ui/useStubGraphApp.ts
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  listOrgs,
  waitForTaskResult,
  getAppConfig,
  type DepMode,
  type GraphNode,
  type NodeContract,
  type NodeInfo,
  type Org,
  type Project,
  type RunTaskResult,
  isTaskStatus,
  type TaskStatus,
  type ProjectFileItem,
  type ProjectTreeEntry,
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
import { useDocs } from './useDocs'
import { useFileDependencies } from './useFileDependencies'
import { useUiPrefs } from './useUiPrefs'
import { useTaskTracking } from './useTaskTracking'
import { useGraphData } from './useGraphData'
import { useProjectSelection } from './useProjectSelection'
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
  DraftEntry,
  TaskBannerItem,
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

  const [applyPatch, setApplyPatch] = useState(false)
  const [prompt, setPrompt] = useState('')

  const [runResult, setRunResult] = useState<RunTaskResult | null>(null)
  const [fullPatch, setFullPatch] = useState<string | null>(null)
  const [patchBusy, setPatchBusy] = useState(false)
  const [runLoadBusy, setRunLoadBusy] = useState(false)
  const [busyCount, setBusyCount] = useState(0)
  const busy = busyCount > 0
  const notif = useNotifications()
  const { error, notifyInfo, setErrorMessage } = notif
  const [focusGraph, setFocusGraph] = useState(false)


  const taskTracking = useTaskTracking()
  const { trackTaskStatus } = taskTracking

  const uiPrefs = useUiPrefs()
  const {
    leftPanelOpen, rightPanelOpen, setLeftPanelOpen, setRightPanelOpen,
    toggleLeftPanel, toggleRightPanel, toggleCompactMode,
  } = uiPrefs
  
  const [workspaceView, setWorkspaceViewState] = useState<WorkspaceView>('graph')
  const [openFilePaths, setOpenFilePaths] = useState<string[]>([])
  const [fileEditorsByPath, setFileEditorsByPath] = useState<Record<string, FileEditorEntry>>({})
  const [activeFilePath, setActiveFilePath] = useState<string | null>(null)
  const fileDeps = useFileDependencies({ activeProject, activeFilePath })
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

  const search = useGraphSearch({ activeProject, notifyInfo, setErrorMessage })
  const { setSearchQuery, setSearchResults } = search


  useEffect(() => {
    if (!orgSelectionStorageFailureMarker) return
    notifyInfo('Organization selection is active for this session only and will not be saved after reload.')
  }, [orgSelectionStorageFailureMarker, notifyInfo])

  useEffect(() => {
    return addStorageErrorListener(() => {
      notifyInfo('Local storage unavailable — preferences will not be saved.')
    })
  }, [notifyInfo])


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

  const selectionNav = useSelectionNav({
    selectedPath, pinnedPaths, backStack, forwardStack, PIN_LIMIT,
    selectedPathRef, backStackRef, forwardStackRef, selectionTrailRef,
    setSelectedPath, setPinnedPaths, setBackStack, setForwardStack, setSelectionTrail,
    setSelection, resetForSelectionChange,
  })
  const { onClearSelection, canGoBack, canGoForward, goBack, goForward } = selectionNav

  const { projectsQuery, runsQuery, graphQuery, nodeQuery } = useGraphData({
    selectedOrgId, activeProject, selectedPath, graphMode, graphHops, graphLimitN,
    graphLocalMax, nodeSeqRef, setErrorMessage, setNodeInfo, setContract,
  })

  const { selectProjectLocal, clearActiveProject, onSelectOrg } = useProjectSelection({
    orgs, activeProject, selectedOrgId, queryClient, applyOrgSelection, persistWorkspace,
    prevOrgIdRef, nodeSeqRef, workspaceBootingRef, selectedPathRef, backStackRef,
    forwardStackRef, selectionTrailRef, setActiveProject, setSelectedPath, setBackStack,
    setForwardStack, setSelectionTrail, setPinnedPaths, setNodeInfo, setContract,
    setRunResult, setFullPatch, setPrompt, setErrorMessage, setSearchQuery, setSearchResults,
    setGraphMode, setGraphLimitN, setGraphHops, setGraphLocalMax, setWorkspaceViewState,
    setOpenFilePaths, setFileEditorsByPath, setActiveFilePath, setPendingClosePath,
    setPendingClosePaths, setPendingActivePath, setPendingReloadPath, setPendingView,
    setConfirmOpen, setConfirmReason,
  })

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

  const docsApi = useDocs({ activeProject, notifyInfo, setErrorMessage, trackTaskStatus })

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


  const fileEditors = useFileEditors({
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
  const { loadFileEditor, openFileEditor, queueMutationIndexingPoll, closeFileEditorPaths, setActiveFileContent } = fileEditors

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

  const projectActions = useProjectActions({
    activeProject, allowLocalRootPath, newName, newArchive, newPath, selectedOrgId,
    selectedPathRef, projectsQuery, queryClient, runOp, runOpThrow, selectProjectLocal,
    clearActiveProject, trackTaskStatus, queueMutationIndexingPoll, setSelection,
    setNewArchive, setNewPath, setPinnedPaths, setActiveFilePath, setOpenFilePaths,
    setFileEditorsByPath, setFileSaveBanner, setGraphStale, setGraphStaleMessage,
  })

  const runActions = useGraphRunActions({
    config,
    activeProject, applyPatch, contract, graph, graphMode, nodeInfo, notifyInfo, prompt,
    queryClient, runOp, runResult, selectedOrgId, selectedPath,
    setErrorMessage, setFullPatch, setGraphMode, setGraphStale, setGraphStaleMessage,
    setPatchBusy, setRightPanelOpen, setRunLoadBusy, setRunResult, setSelection, trackTaskStatus,
  })

  const fileTabs = useFileTabs({
    activeFilePath, openFilePaths, fileEditorsByPath, workspaceView, selectedPathRef,
    closeFileEditorPaths, openFileEditor, setSelection,
    setConfirmOpen, setConfirmReason, setPendingClosePath, setPendingClosePaths,
    setPendingActivePath, setPendingView, setWorkspaceViewState,
    setFindRequestId, setReplaceRequestId, setOutlineRequestId,
  })
  const { toggleWorkspaceView, requestFindInFile, requestReplaceInFile, requestOutlineInFile } = fileTabs

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
    ...taskTracking,
    ...uiPrefs,
    ...fileDeps,
    ...docsApi,
    ...config,
    ...fileEditors,
    ...notif,
    ...selectionNav,
    ...fileTabs,
    ...search,
    ...projectActions,
    ...runActions,
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
    fileSaveBanner,
    graphStale,
    graphStaleMessage,
    draftRestore,
    allowLocalRootPath,
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
    pendingJump,
    runs,
    newName,
    newArchive,
    newPath,
    selectedPath,
    selectedInGraph,
    nodeInfo,
    contract,
    applyPatch,
    prompt,
    runResult,
    fullPatch,
    busy: mutationBusy,
    graphBusy,
    nodeBusy,
    patchBusy,
    runLoadBusy,
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

    setApplyPatch,
    setPrompt,

    focusGraph,
    setFocusGraph,
    workspaceView,
    paletteOpen,
    setPaletteOpen,
    registerUndoRedoHandlers,

    selectionTrail,

    pinnedPaths,
    
    // actions

    // derived
    canRun,
  }
}
