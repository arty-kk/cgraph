// frontend/src/ui/useStubGraphApp.ts
import { useCallback, useEffect, useMemo, useRef } from 'react'
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
import { useWorkspace } from './workspace'
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

  const ws = useWorkspace()
  const {
    selectedOrgId, orgSelectionStorageFailureMarker, activeProject, newName, newArchive, newPath,
    graphMode, graphLimitN, graphHops, graphLocalMax,
    gotoLineRequestId, findRequestId, replaceRequestId, outlineRequestId,
    backStack, forwardStack, selectionTrail, pinnedPaths, selectedPath,
    paletteOpen, nodeInfo, contract, applyPatch, prompt,
    runResult, fullPatch, patchBusy, runLoadBusy, busyCount, focusGraph,
    workspaceView, openFilePaths, fileEditorsByPath, activeFilePath,
    fileSaveBanner, graphStale, graphStaleMessage, draftsByPath, draftRestore,
    pendingClosePath, pendingClosePaths, pendingActivePath, pendingReloadPath, pendingJump,
    confirmOpen, confirmReason, pendingView,
  } = ws.state
  const {
    setSelectedOrgId: setSelectedOrgIdState,
    setOrgSelectionStorageFailureMarker, setActiveProject, setNewName, setNewArchive, setNewPath,
    setGraphMode, setGraphLimitN, setGraphHops, setGraphLocalMax,
    setGotoLineRequestId, setFindRequestId, setReplaceRequestId, setOutlineRequestId,
    setBackStack, setForwardStack, setSelectionTrail, setPinnedPaths, setSelectedPath,
    setPaletteOpen, setNodeInfo, setContract, setApplyPatch, setPrompt,
    setRunResult, setFullPatch, setPatchBusy, setRunLoadBusy, setBusyCount, setFocusGraph,
    setWorkspaceView: setWorkspaceViewState, setOpenFilePaths, setFileEditorsByPath, setActiveFilePath,
    setFileSaveBanner, setGraphStale, setGraphStaleMessage, setDraftsByPath, setDraftRestore,
    setPendingClosePath, setPendingClosePaths, setPendingActivePath, setPendingReloadPath, setPendingJump,
    setConfirmOpen, setConfirmReason, setPendingView,
  } = ws.setters
  const prevOrgIdRef = useRef<number | null>(null)

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


  const nodeSeqRef = useRef(0)




  const orgs = orgsQuery.data ?? []
  const allowLocalRootPath = configQuery.data?.allow_local_root_path ?? null

  useOrgAutoSelect({ orgs, selectedOrgId, applyOrgSelection, orgStorageKey: ORG_STORAGE_KEY })

  const selectedPathRef = useRef<string | null>(null)
  const prevActiveFilePathRef = useRef<string | null>(null)
  const backStackRef = useRef<string[]>([])
  const forwardStackRef = useRef<string[]>([])
  const selectionTrailRef = useRef<string[]>([])


  const PIN_LIMIT = 3


  useEffect(() => { selectedPathRef.current = selectedPath }, [selectedPath])
  useEffect(() => { backStackRef.current = backStack }, [backStack])
  useEffect(() => { forwardStackRef.current = forwardStack }, [forwardStack])
  useEffect(() => { selectionTrailRef.current = selectionTrail }, [selectionTrail])

  const config = useAppConfig()


  const busy = busyCount > 0
  const notif = useNotifications()
  const { error, notifyInfo, setErrorMessage } = notif


  const taskTracking = useTaskTracking()

  const uiPrefs = useUiPrefs()
  const {
    leftPanelOpen, rightPanelOpen, setLeftPanelOpen, setRightPanelOpen,
    toggleLeftPanel, toggleRightPanel, toggleCompactMode,
  } = uiPrefs
  
  const fileDeps = useFileDependencies({ activeProject, activeFilePath })


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
    PIN_LIMIT,
    nodeSeqRef, selectedPathRef, backStackRef, forwardStackRef, selectionTrailRef,
    workspaceBootingRef, workspaceSaveTimerRef, draftSaveTimerRef, restoredEditorRef, draftPromptedRef,
    setSearchQuery, setSearchResults,
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
    orgs, queryClient, applyOrgSelection, persistWorkspace,
    prevOrgIdRef, nodeSeqRef, workspaceBootingRef, selectedPathRef, backStackRef,
    forwardStackRef, selectionTrailRef, setSearchQuery, setSearchResults,
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
