import { useCallback, useEffect } from 'react'
import type { Dispatch, MutableRefObject, SetStateAction } from 'react'
import type { QueryClient } from '@tanstack/react-query'
import type {
  Project,
  Org,
  NodeInfo,
  NodeContract,
  RunTaskResult,
  NodeSearchItem,
} from '@/api'
import type { GraphMode, WorkspaceView, FileEditorEntry } from '../internal'

type Params = {
  orgs: Org[]
  activeProject: Project | null
  selectedOrgId: number | null
  queryClient: QueryClient
  applyOrgSelection: (orgId: number | null) => void
  persistWorkspace: (projectId: number) => void
  prevOrgIdRef: MutableRefObject<number | null>
  nodeSeqRef: MutableRefObject<number>
  workspaceBootingRef: MutableRefObject<boolean>
  selectedPathRef: MutableRefObject<string | null>
  backStackRef: MutableRefObject<string[]>
  forwardStackRef: MutableRefObject<string[]>
  selectionTrailRef: MutableRefObject<string[]>
  setActiveProject: Dispatch<SetStateAction<Project | null>>
  setSelectedPath: Dispatch<SetStateAction<string | null>>
  setBackStack: Dispatch<SetStateAction<string[]>>
  setForwardStack: Dispatch<SetStateAction<string[]>>
  setSelectionTrail: Dispatch<SetStateAction<string[]>>
  setPinnedPaths: Dispatch<SetStateAction<string[]>>
  setNodeInfo: Dispatch<SetStateAction<NodeInfo | null>>
  setContract: Dispatch<SetStateAction<NodeContract | null>>
  setRunResult: Dispatch<SetStateAction<RunTaskResult | null>>
  setFullPatch: Dispatch<SetStateAction<string | null>>
  setPrompt: Dispatch<SetStateAction<string>>
  setErrorMessage: (message: string | null) => void
  setSearchQuery: Dispatch<SetStateAction<string>>
  setSearchResults: Dispatch<SetStateAction<NodeSearchItem[]>>
  setGraphMode: Dispatch<SetStateAction<GraphMode>>
  setGraphLimitN: Dispatch<SetStateAction<number>>
  setGraphHops: Dispatch<SetStateAction<number>>
  setGraphLocalMax: Dispatch<SetStateAction<number>>
  setWorkspaceViewState: Dispatch<SetStateAction<WorkspaceView>>
  setOpenFilePaths: Dispatch<SetStateAction<string[]>>
  setFileEditorsByPath: Dispatch<SetStateAction<Record<string, FileEditorEntry>>>
  setActiveFilePath: Dispatch<SetStateAction<string | null>>
  setPendingClosePath: Dispatch<SetStateAction<string | null>>
  setPendingClosePaths: Dispatch<SetStateAction<string[]>>
  setPendingActivePath: Dispatch<SetStateAction<string | null>>
  setPendingReloadPath: Dispatch<SetStateAction<string | null>>
  setPendingView: Dispatch<SetStateAction<WorkspaceView | null>>
  setConfirmOpen: Dispatch<SetStateAction<boolean>>
  setConfirmReason: Dispatch<SetStateAction<string | null>>
}

/**
 * Project + org selection: select/clear the active project (resetting all
 * dependent workspace/selection/run state) and switch orgs. Extracted verbatim
 * from useStubGraphApp; all the reset targets are passed in.
 */
export function useProjectSelection({
  orgs,
  activeProject,
  selectedOrgId,
  queryClient,
  applyOrgSelection,
  persistWorkspace,
  prevOrgIdRef,
  nodeSeqRef,
  workspaceBootingRef,
  selectedPathRef,
  backStackRef,
  forwardStackRef,
  selectionTrailRef,
  setActiveProject,
  setSelectedPath,
  setBackStack,
  setForwardStack,
  setSelectionTrail,
  setPinnedPaths,
  setNodeInfo,
  setContract,
  setRunResult,
  setFullPatch,
  setPrompt,
  setErrorMessage,
  setSearchQuery,
  setSearchResults,
  setGraphMode,
  setGraphLimitN,
  setGraphHops,
  setGraphLocalMax,
  setWorkspaceViewState,
  setOpenFilePaths,
  setFileEditorsByPath,
  setActiveFilePath,
  setPendingClosePath,
  setPendingClosePaths,
  setPendingActivePath,
  setPendingReloadPath,
  setPendingView,
  setConfirmOpen,
  setConfirmReason,
}: Params) {
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

  return { selectProjectLocal, clearActiveProject, onSelectOrg }
}
