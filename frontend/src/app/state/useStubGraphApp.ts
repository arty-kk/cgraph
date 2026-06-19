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
import { useFileEditors, useFileTabs, useFileDependencies, useFileMeta } from './files'
import {
  useProjectActions,
  useProjectSelection,
  useWorkspaceSession,
  useOrgAutoSelect,
} from './projects'
import { useGraphData, useGraphSearch, useGraphRunActions } from './graph'
import { useSelectionNav, useDerivedAppState, useGlobalKeyboard } from './interaction'
import { useAppConfig, useUiPrefs } from './settings'
import { useNotifications, useTaskTracking, useDocs } from './session'
import {
  addStorageErrorListener,
  safeStorageGet,
  safeStorageRemove,
  safeStorageSet,
} from '@/shared/lib/storage'
import {
  GRAPH_NOT_BUILT_WARNING,
  pickCreatedSnapshotProject,
  getRunGraphStaleState,
  getMutationTaskSeed,
} from './internal'
import type {
  GraphMode,
  WorkspaceView,
  FileEditorEntry,
  PendingFileJump,
  NotificationKind,
  NotificationItem,
  IndexStatus,
  FileSaveBanner,
  DraftEntry,
  TaskBannerItem,
  UseStubGraphAppOptions,
} from './internal'

// Preserve the existing public surface for external consumers (Notifications, tests).
export type {
  FileEditorEntry,
  PendingFileJump,
  NotificationKind,
  NotificationItem,
} from './internal'
export {
  GRAPH_NOT_BUILT_WARNING,
  pickCreatedSnapshotProject,
  getRunGraphStaleState,
  getMutationTaskSeed,
} from './internal'

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

  useOrgAutoSelect({ orgs, selectedOrgId, applyOrgSelection, orgStorageKey: ORG_STORAGE_KEY })

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


  const search = useGraphSearch({ activeProject })
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


  const {
    setSelection, resetForSelectionChange, buildWorkspaceState, persistWorkspace, hasDirtyEditors,
  } = useWorkspaceSession({
    activeProject, activeFilePath, selectedPath, workspaceView, backStack, forwardStack,
    selectionTrail, pinnedPaths, graphMode, graphLimitN, graphHops, graphLocalMax,
    draftsByPath, fileEditorsByPath, openFilePaths, PIN_LIMIT,
    nodeSeqRef, selectedPathRef, backStackRef, forwardStackRef, selectionTrailRef,
    workspaceBootingRef, workspaceSaveTimerRef, draftSaveTimerRef, restoredEditorRef, draftPromptedRef,
    setSelectedPath, setBackStack, setForwardStack, setSelectionTrail, setPinnedPaths,
    setNodeInfo, setContract, setRunResult, setFullPatch, setPrompt,
    setSearchQuery, setSearchResults, setGraphMode, setGraphLimitN, setGraphHops, setGraphLocalMax,
    setWorkspaceViewState, setOpenFilePaths, setFileEditorsByPath, setActiveFilePath,
    setDraftRestore, setDraftsByPath, setFileSaveBanner, setGraphStale, setGraphStaleMessage,
  })

  const selectionNav = useSelectionNav({
    selectedPath, pinnedPaths, backStack, forwardStack, PIN_LIMIT,
    selectedPathRef, backStackRef, forwardStackRef, selectionTrailRef,
    setSelectedPath, setPinnedPaths, setBackStack, setForwardStack, setSelectionTrail,
    setSelection, resetForSelectionChange,
  })
  const { onClearSelection, canGoBack, canGoForward, goBack, goForward } = selectionNav

  const { projectsQuery, runsQuery, graphQuery, nodeQuery } = useGraphData({
    selectedOrgId, activeProject, selectedPath, graphMode, graphHops, graphLimitN,
    graphLocalMax, nodeSeqRef, setNodeInfo, setContract,
  })

  const { selectProjectLocal, clearActiveProject, onSelectOrg } = useProjectSelection({
    orgs, activeProject, selectedOrgId, queryClient, applyOrgSelection, persistWorkspace,
    prevOrgIdRef, nodeSeqRef, workspaceBootingRef, selectedPathRef, backStackRef,
    forwardStackRef, selectionTrailRef, setActiveProject, setSelectedPath, setBackStack,
    setForwardStack, setSelectionTrail, setPinnedPaths, setNodeInfo, setContract,
    setRunResult, setFullPatch, setPrompt, setSearchQuery, setSearchResults,
    setGraphMode, setGraphLimitN, setGraphHops, setGraphLocalMax, setWorkspaceViewState,
    setOpenFilePaths, setFileEditorsByPath, setActiveFilePath, setPendingClosePath,
    setPendingClosePaths, setPendingActivePath, setPendingReloadPath, setPendingView,
    setConfirmOpen, setConfirmReason,
  })

  const projects = projectsQuery.data ?? []
  const runs = runsQuery.data ?? []
  const graph = graphQuery.data ?? null

  const { fileMetaByPath, registerFileMeta } = useFileMeta({ activeProject })


  const docsApi = useDocs({ activeProject })


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
    activeProject, selectedOrgId, queryClient, draftPromptedRef,
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
    clearActiveProject, queueMutationIndexingPoll, setSelection,
    setNewArchive, setNewPath, setPinnedPaths, setActiveFilePath, setOpenFilePaths,
    setFileEditorsByPath, setFileSaveBanner, setGraphStale, setGraphStaleMessage,
  })

  const runActions = useGraphRunActions({
    config,
    activeProject, applyPatch, contract, graph, graphMode, nodeInfo, prompt,
    queryClient, runOp, runResult, selectedOrgId, selectedPath,
    setFullPatch, setGraphMode, setGraphStale, setGraphStaleMessage,
    setPatchBusy, setRightPanelOpen, setRunLoadBusy, setRunResult, setSelection,
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

  const derived = useDerivedAppState({
    selectedPath, graph, activeProject, activeFilePath, fileEditorsByPath, draftsByPath,
    contract, nodeInfo, prompt, busy, graphQuery, nodeQuery, projectsQuery,
  })

  return {
    fileMetaByPath,
    registerFileMeta,
    ...derived,
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
    fileSaveBanner,
    graphStale,
    graphStaleMessage,
    draftRestore,
    allowLocalRootPath,
    fileEditorOpen,
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
    nodeInfo,
    contract,
    applyPatch,
    prompt,
    runResult,
    fullPatch,
    busy: derived.mutationBusy,
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
  }
}
