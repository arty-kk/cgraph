import { useCallback, useEffect, useMemo } from 'react'
import type { Dispatch, MutableRefObject, SetStateAction } from 'react'
import type { Project, NodeInfo, NodeContract, RunTaskResult, NodeSearchItem } from '@/api'
import {
  safeStorageGet,
  safeStorageGetJson,
  safeStorageRemove,
  safeStorageSet,
} from '@/shared/lib/storage'
import {
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
  type WorkspaceStateV1,
  type WorkspaceStateV2,
  type WorkspaceStateV3,
  type DraftEntry,
  type FileEditorEntry,
  type GraphMode,
  type WorkspaceView,
} from './useStubGraphApp.internal'

type Params = {
  activeProject: Project | null
  activeFilePath: string | null
  selectedPath: string | null
  workspaceView: WorkspaceView
  backStack: string[]
  forwardStack: string[]
  selectionTrail: string[]
  pinnedPaths: string[]
  graphMode: GraphMode
  graphLimitN: number
  graphHops: number
  graphLocalMax: number
  draftsByPath: Record<string, DraftEntry>
  fileEditorsByPath: Record<string, FileEditorEntry>
  openFilePaths: string[]
  PIN_LIMIT: number
  nodeSeqRef: MutableRefObject<number>
  selectedPathRef: MutableRefObject<string | null>
  backStackRef: MutableRefObject<string[]>
  forwardStackRef: MutableRefObject<string[]>
  selectionTrailRef: MutableRefObject<string[]>
  workspaceBootingRef: MutableRefObject<boolean>
  workspaceSaveTimerRef: MutableRefObject<number | null>
  draftSaveTimerRef: MutableRefObject<number | null>
  restoredEditorRef: MutableRefObject<boolean>
  draftPromptedRef: MutableRefObject<Set<string>>
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
  setDraftRestore: Dispatch<SetStateAction<{ path: string; draft: DraftEntry } | null>>
  setDraftsByPath: Dispatch<SetStateAction<Record<string, DraftEntry>>>
  setFileSaveBanner: Dispatch<SetStateAction<import('./useStubGraphApp.internal').FileSaveBanner | null>>
  setGraphStale: Dispatch<SetStateAction<boolean>>
  setGraphStaleMessage: Dispatch<SetStateAction<string | null>>
}

/**
 * Workspace session core: build/persist workspace state, restore it on project
 * load, manage drafts, plus the selection setter + per-selection reset.
 * Extracted verbatim from useStubGraphApp; all state it reads/writes is passed
 * in. Returns setSelection/reset + the persistence helpers.
 */
export function useWorkspaceSession({
  activeProject,
  activeFilePath,
  selectedPath,
  workspaceView,
  backStack,
  forwardStack,
  selectionTrail,
  pinnedPaths,
  graphMode,
  graphLimitN,
  graphHops,
  graphLocalMax,
  draftsByPath,
  fileEditorsByPath,
  openFilePaths,
  PIN_LIMIT,
  nodeSeqRef,
  selectedPathRef,
  backStackRef,
  forwardStackRef,
  selectionTrailRef,
  workspaceBootingRef,
  workspaceSaveTimerRef,
  draftSaveTimerRef,
  restoredEditorRef,
  draftPromptedRef,
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
  setDraftRestore,
  setDraftsByPath,
  setFileSaveBanner,
  setGraphStale,
  setGraphStaleMessage,
}: Params) {
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

  return { setSelection, resetForSelectionChange, buildWorkspaceState, persistWorkspace, hasDirtyEditors }
}
