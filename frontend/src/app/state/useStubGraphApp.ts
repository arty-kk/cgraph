// frontend/src/ui/useStubGraphApp.ts
import { useCallback, useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { listOrgs, getAppConfig, type Org, setSelectedOrgId } from '@/api'
import { extractError } from '@/shared/lib/errors'
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
import { addStorageErrorListener, safeStorageRemove, safeStorageSet } from '@/shared/lib/storage'
import type { UseStubGraphAppOptions } from './internal'

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
    runResult, fullPatch, patchBusy, runLoadBusy, focusGraph,
    workspaceView, openFilePaths, fileEditorsByPath, activeFilePath,
    fileSaveBanner, graphStale, graphStaleMessage, draftRestore, pendingJump,
    confirmOpen, confirmReason,
  } = ws.state
  const {
    setSelectedOrgId: setSelectedOrgIdState,
    setOrgSelectionStorageFailureMarker, setNewName, setNewArchive, setNewPath,
    setGraphMode, setGraphLimitN, setGraphHops, setGraphLocalMax,
    setPaletteOpen, setApplyPatch, setPrompt, setBusyCount, setFocusGraph,
    setOpenFilePaths, setFileEditorsByPath, setActiveFilePath,
    setPendingClosePath, setPendingClosePaths, setPendingActivePath, setPendingReloadPath,
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


  const notif = useNotifications()
  const { notifyInfo, setErrorMessage } = notif


  const taskTracking = useTaskTracking()

  const uiPrefs = useUiPrefs()
  const {
    leftPanelOpen, rightPanelOpen, setLeftPanelOpen, setRightPanelOpen,
    toggleLeftPanel, toggleRightPanel, toggleCompactMode,
  } = uiPrefs
  
  const fileDeps = useFileDependencies()


  const search = useGraphSearch()
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
    setSelection, resetForSelectionChange, persistWorkspace,
  } = useWorkspaceSession({
    PIN_LIMIT,
    nodeSeqRef, selectedPathRef, backStackRef, forwardStackRef, selectionTrailRef,
    workspaceBootingRef, workspaceSaveTimerRef, draftSaveTimerRef, restoredEditorRef, draftPromptedRef,
    setSearchQuery, setSearchResults,
  })

  const selectionNav = useSelectionNav({
    PIN_LIMIT, selectedPathRef, backStackRef, forwardStackRef, selectionTrailRef,
    setSelection, resetForSelectionChange,
  })
  const { onClearSelection, canGoBack, canGoForward, goBack, goForward } = selectionNav

  const { projectsQuery, runsQuery, graphQuery, nodeQuery } = useGraphData({ nodeSeqRef })

  const { selectProjectLocal, clearActiveProject, onSelectOrg } = useProjectSelection({
    orgs, queryClient, applyOrgSelection, persistWorkspace,
    prevOrgIdRef, nodeSeqRef, workspaceBootingRef, selectedPathRef, backStackRef,
    forwardStackRef, selectionTrailRef, setSearchQuery, setSearchResults,
  })

  const projects = projectsQuery.data ?? []
  const runs = runsQuery.data ?? []
  const graph = graphQuery.data ?? null

  const { fileMetaByPath, registerFileMeta } = useFileMeta()


  const docsApi = useDocs()


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


  const fileEditors = useFileEditors({ queryClient, draftPromptedRef })
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
    allowLocalRootPath, selectedPathRef, projectsQuery, queryClient, runOp, runOpThrow,
    selectProjectLocal, clearActiveProject, queueMutationIndexingPoll, setSelection,
  })

  const runActions = useGraphRunActions({
    config, graph, queryClient, runOp, setRightPanelOpen, setSelection,
  })

  const fileTabs = useFileTabs({
    selectedPathRef, closeFileEditorPaths, openFileEditor, setSelection,
  })
  const { toggleWorkspaceView, requestFindInFile, requestReplaceInFile, requestOutlineInFile } = fileTabs

  const fileEditorOpen = workspaceView === 'editor'

  const { registerUndoRedoHandlers } = useGlobalKeyboard({
    canGoBack, canGoForward, goBack, goForward,
    onClearSelection, onFocusSearch,
    toggleWorkspaceView, graph,
    leftPanelOpen, rightPanelOpen, setLeftPanelOpen, setRightPanelOpen,
    toggleLeftPanel, toggleRightPanel, toggleCompactMode,
    fileEditorOpen, openFileEditor,
    requestFindInFile, requestReplaceInFile, requestOutlineInFile,
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

  const derived = useDerivedAppState({ graph, graphQuery, nodeQuery, projectsQuery })

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
