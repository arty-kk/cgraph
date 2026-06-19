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
import { useNotifications } from '../session'
import { useWorkspace } from '../workspace'

type Params = {
  orgs: Org[]
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
  setSearchQuery: Dispatch<SetStateAction<string>>
  setSearchResults: Dispatch<SetStateAction<NodeSearchItem[]>>
}

/**
 * Project + org selection: select/clear the active project (resetting all
 * dependent workspace/selection/run state) and switch orgs. Extracted verbatim
 * from useStubGraphApp; all the reset targets are passed in.
 */
export function useProjectSelection({
  orgs,
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
  setSearchQuery,
  setSearchResults,
}: Params) {
  const { setErrorMessage } = useNotifications()
  const ws = useWorkspace()
  const { activeProject, selectedOrgId } = ws.state
  const {
    setActiveProject, setSelectedPath, setBackStack, setForwardStack, setSelectionTrail,
    setPinnedPaths, setNodeInfo, setContract, setRunResult, setFullPatch, setPrompt,
    setGraphMode, setGraphLimitN, setGraphHops, setGraphLocalMax,
    setWorkspaceView: setWorkspaceViewState,
    setOpenFilePaths, setFileEditorsByPath, setActiveFilePath,
    setPendingClosePath, setPendingClosePaths, setPendingActivePath, setPendingReloadPath, setPendingView,
    setConfirmOpen, setConfirmReason,
  } = ws.setters
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
