// frontend/src/ui/useStubGraphApp.ts
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createProject,
  deleteProject,
  getContract,
  getGraph,
  getLocalGraph,
  getNode,
  getRun,
  getRunPatch,
  applyRunPatch,
  listProjects,
  listRuns,
  deleteRun,
  runTask,
  scanProject,
  searchNodes,
  listProjectFiles,
  getProjectDocs,
  buildProjectDocs,
  searchProjectSemantic,
  searchProjectText,
  getFileContent,
  updateFileContent,
  createFile,
  renameFile,
  deleteFile,
  type DepMode,
  type GraphData,
  type GraphNode,
  type FileContent,
  type FileSaveResult,
  type Mode,
  type NodeContract,
  type NodeInfo,
  type NodeSearchItem,
  type SemanticSearchItem,
  type TextSearchMatch,
  type TextSearchResult,
  type Project,
  type RunRecord,
  type RunTaskBody,
  type RunTaskResult,
  type ProjectFileItem,
  type ProjectDocs,
} from '../api'
import { extractError, getSemanticSearchErrorReason, type SemanticSearchErrorReason } from '../lib/errors'
import { clampInt } from '../lib/number'

type AutoOrMode = 'auto' | Mode
type GraphMode = 'local' | 'full' | 'limit'
type RetrievalMode = 'agentic' | 'pack'
type WorkspaceView = 'graph' | 'editor'

export type FileEditorEntry = {
  path: string
  content: string
  original: string
  truncated: boolean
  busy: boolean
  saving: boolean
  error: string | null
}

export type PendingFileJump = {
  path: string
  line: number
  column: number
}

type WorkspaceStateV1 = {
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

type WorkspaceStateV2 = {
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

type WorkspaceStateV3 = {
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

const WORKSPACE_KEY_PREFIX = 'cs.workspace.v3.'
const LEGACY_WORKSPACE_KEY_PREFIX = 'cs.workspace.v2.'
const LEGACY_WORKSPACE_KEY_PREFIX_V1 = 'cs.workspace.v1.'

function wsKey(projectId: number): string {
  return `${WORKSPACE_KEY_PREFIX}${projectId}`
}

function legacyWsKey(projectId: number): string {
  return `${LEGACY_WORKSPACE_KEY_PREFIX}${projectId}`
}

function legacyWsKeyV1(projectId: number): string {
  return `${LEGACY_WORKSPACE_KEY_PREFIX_V1}${projectId}`
}
function isAnyModalOpen(): boolean {
  if (typeof document === 'undefined') return false
  const raw = document.body?.dataset?.csModalOpenCount
  const n = Number(raw ?? '0')
  return Number.isFinite(n) && n > 0
}

function asStr(v: any): string {
  return typeof v === 'string' ? v.trim() : ''
}

function asStrArr(v: any, limit = 400): string[] {
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

function asInt(v: any, fallback: number, lo: number, hi: number): number {
  const n = Number(v)
  if (!Number.isFinite(n)) return fallback
  const i = Math.trunc(n)
  return Math.max(lo, Math.min(hi, i))
}

function asGraphMode(v: any, fallback: GraphMode): GraphMode {
  const s = asStr(v)
  return s === 'local' || s === 'full' || s === 'limit' ? s : fallback
}

function createFileEditorEntry(path: string, opts: { dirty?: boolean } = {}): FileEditorEntry {
  const dirty = Boolean(opts.dirty)
  return {
    path,
    content: dirty ? '\n' : '',
    original: '',
    truncated: false,
    busy: false,
    saving: false,
    error: null,
  }
}

export type NotificationKind = 'info' | 'error'

export type NotificationItem = {
  id: string
  kind: NotificationKind
  text: string
}

type UseStubGraphAppOptions = {
  onFocusSearch?: () => void
}

export function useStubGraphApp(options: UseStubGraphAppOptions = {}) {
  const { onFocusSearch } = options
  const workspaceBootingRef = useRef(false)
  const workspaceSaveTimerRef = useRef<number | null>(null)
  const restoredEditorRef = useRef(false)
  const undoRedoHandlersRef = useRef<{ undo?: () => void; redo?: () => void } | null>(null)

  const queryClient = useQueryClient()

  const [activeProject, setActiveProject] = useState<Project | null>(null)

  const nodeSeqRef = useRef(0)
  const searchSeqRef = useRef(0)

  const [newName, setNewName] = useState('my-project')
  const [newPath, setNewPath] = useState('')

  const [graphMode, setGraphMode] = useState<GraphMode>('limit')
  const [graphLimitN, setGraphLimitN] = useState<number>(2000)
  const [graphHops, setGraphHops] = useState<number>(2)
  const [graphLocalMax, setGraphLocalMax] = useState<number>(400)

  const [gotoLineRequestId, setGotoLineRequestId] = useState(0)
  const [findRequestId, setFindRequestId] = useState(0)
  const [replaceRequestId, setReplaceRequestId] = useState(0)
  const [outlineRequestId, setOutlineRequestId] = useState(0)

  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<NodeSearchItem[]>([])
  const [searchSemanticResults, setSearchSemanticResults] = useState<SemanticSearchItem[]>([])
  const [searchBusy, setSearchBusy] = useState(false)
  const [semanticSearchEnabled, setSemanticSearchEnabled] = useState(false)
  const [semanticSearchFallbackUsed, setSemanticSearchFallbackUsed] = useState(false)
  const [semanticSearchUnavailableReason, setSemanticSearchUnavailableReason] = useState<SemanticSearchErrorReason | null>(null)

  const textSearchSeqRef = useRef(0)
  const [textSearchQuery, setTextSearchQuery] = useState('')
  const [textSearchResults, setTextSearchResults] = useState<TextSearchMatch[]>([])
  const [textSearchMeta, setTextSearchMeta] = useState<TextSearchResult['meta'] | null>(null)
  const [textSearchBusy, setTextSearchBusy] = useState(false)
  const [textSearchCaseSensitive, setTextSearchCaseSensitive] = useState(false)
  const [textSearchPrefix, setTextSearchPrefix] = useState('')
  const [textSearchError, setTextSearchError] = useState<string | null>(null)

  useEffect(() => {
    if (searchQuery.trim()) return
    if (searchResults.length === 0) return
    setSearchResults([])
  }, [searchQuery, searchResults.length])

  useEffect(() => {
    if (searchQuery.trim()) return
    if (searchSemanticResults.length === 0) return
    setSearchSemanticResults([])
  }, [searchQuery, searchSemanticResults.length])

  useEffect(() => {
    setSearchResults([])
    setSearchSemanticResults([])
    setSemanticSearchFallbackUsed(false)
  }, [semanticSearchEnabled])

  useEffect(() => {
    if (textSearchQuery.trim()) return
    if (textSearchResults.length === 0 && !textSearchMeta && !textSearchError) return
    setTextSearchResults([])
    setTextSearchMeta(null)
    setTextSearchError(null)
  }, [textSearchError, textSearchMeta, textSearchQuery, textSearchResults.length])

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

  const [mode, setMode] = useState<AutoOrMode>('auto')
  const [depth, setDepth] = useState<number>(1)
  const [depMode, setDepMode] = useState<DepMode>('contracts')
  const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>(() => {
    try {
      const v = (localStorage.getItem('cs.ui.retrievalMode') || '').trim()
      return v === 'pack' ? 'pack' : 'agentic'
    } catch {
      return 'agentic'
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem('cs.ui.retrievalMode', retrievalMode)
    } catch {}
  }, [retrievalMode])

  // Advanced context settings (persisted)
  const [agenticMaxCalls, setAgenticMaxCalls] = useState<number>(() => {
    try { return Number(localStorage.getItem('cs.ui.agentic.maxCalls') || '24') || 24 } catch { return 24 }
  })
  const [agenticMaxFileChars, setAgenticMaxFileChars] = useState<number>(() => {
    try { return Number(localStorage.getItem('cs.ui.agentic.maxFileChars') || '200000') || 200000 } catch { return 200000 }
  })
  const [agenticMaxTotalToolOutputChars, setAgenticMaxTotalToolOutputChars] = useState<number>(() => {
    try { return Number(localStorage.getItem('cs.ui.agentic.maxToolChars') || '2000000') || 2000000 } catch { return 2000000 }
  })
  const [agenticTemperature, setAgenticTemperature] = useState<number>(() => {
    try { return Number(localStorage.getItem('cs.ui.agentic.temperature') || '0') || 0 } catch { return 0 }
  })
  const [packMaxFiles, setPackMaxFiles] = useState<number>(() => {
    try { return Number(localStorage.getItem('cs.ui.pack.maxFiles') || '25') || 25 } catch { return 25 }
  })
  const [packMaxCharsPerFile, setPackMaxCharsPerFile] = useState<number>(() => {
    try { return Number(localStorage.getItem('cs.ui.pack.maxCharsPerFile') || '200000') || 200000 } catch { return 200000 }
  })
  const [packMaxTotalChars, setPackMaxTotalChars] = useState<number>(() => {
    try { return Number(localStorage.getItem('cs.ui.pack.maxTotalChars') || '2000000') || 2000000 } catch { return 2000000 }
  })
  useEffect(() => { try { localStorage.setItem('cs.ui.agentic.maxCalls', String(agenticMaxCalls)) } catch {} }, [agenticMaxCalls])
  useEffect(() => { try { localStorage.setItem('cs.ui.agentic.maxFileChars', String(agenticMaxFileChars)) } catch {} }, [agenticMaxFileChars])
  useEffect(() => { try { localStorage.setItem('cs.ui.agentic.maxToolChars', String(agenticMaxTotalToolOutputChars)) } catch {} }, [agenticMaxTotalToolOutputChars])
  useEffect(() => { try { localStorage.setItem('cs.ui.agentic.temperature', String(agenticTemperature)) } catch {} }, [agenticTemperature])
  useEffect(() => { try { localStorage.setItem('cs.ui.pack.maxFiles', String(packMaxFiles)) } catch {} }, [packMaxFiles])
  useEffect(() => { try { localStorage.setItem('cs.ui.pack.maxCharsPerFile', String(packMaxCharsPerFile)) } catch {} }, [packMaxCharsPerFile])
  useEffect(() => { try { localStorage.setItem('cs.ui.pack.maxTotalChars', String(packMaxTotalChars)) } catch {} }, [packMaxTotalChars])

  const [applyPatch, setApplyPatch] = useState(false)
  const [prompt, setPrompt] = useState('')

  const [runResult, setRunResult] = useState<RunTaskResult | null>(null)
  const [fullPatch, setFullPatch] = useState<string | null>(null)
  const [patchBusy, setPatchBusy] = useState(false)
  const [runLoadBusy, setRunLoadBusy] = useState(false)
  const [busyCount, setBusyCount] = useState(0)
  const busy = busyCount > 0
  const [error, setError] = useState<string | null>(null)
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [focusGraph, setFocusGraph] = useState(false)

  const [compactMode, setCompactMode] = useState<boolean>(() => {
    try { return (localStorage.getItem('cs.ui.compactMode') || '0') === '1' } catch { return false }
  })
  useEffect(() => {
    try { localStorage.setItem('cs.ui.compactMode', compactMode ? '1' : '0') } catch {}
  }, [compactMode])
  const toggleCompactMode = useCallback(() => setCompactMode((v) => !v), [])

  const [leftPanelOpen, setLeftPanelOpen] = useState<boolean>(() => {
    try { return (localStorage.getItem('cs.ui.leftPanelOpen') || '1') !== '0' } catch { return true }
  })
  const [rightPanelOpen, setRightPanelOpen] = useState<boolean>(() => {
    try { return (localStorage.getItem('cs.ui.rightPanelOpen') || '1') !== '0' } catch { return true }
  })
  useEffect(() => { try { localStorage.setItem('cs.ui.leftPanelOpen', leftPanelOpen ? '1' : '0') } catch {} }, [leftPanelOpen])
  useEffect(() => { try { localStorage.setItem('cs.ui.rightPanelOpen', rightPanelOpen ? '1' : '0') } catch {} }, [rightPanelOpen])

  const toggleLeftPanel = useCallback(() => setLeftPanelOpen((v) => !v), [])
  const toggleRightPanel = useCallback(() => setRightPanelOpen((v) => !v), [])
  
  const [workspaceView, setWorkspaceViewState] = useState<WorkspaceView>('graph')
  const [openFilePaths, setOpenFilePaths] = useState<string[]>([])
  const [fileEditorsByPath, setFileEditorsByPath] = useState<Record<string, FileEditorEntry>>({})
  const [activeFilePath, setActiveFilePath] = useState<string | null>(null)
  const [pendingClosePath, setPendingClosePath] = useState<string | null>(null)
  const [pendingActivePath, setPendingActivePath] = useState<string | null>(null)
  const [pendingReloadPath, setPendingReloadPath] = useState<string | null>(null)
  const [pendingJump, setPendingJump] = useState<PendingFileJump | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [confirmReason, setConfirmReason] = useState<string | null>(null)
  const [pendingView, setPendingView] = useState<WorkspaceView | null>(null)
  const FILE_EDITOR_MAX_CHARS = 200_000

  const hasDirtyEditors = useMemo(() => {
    return Object.values(fileEditorsByPath).some((entry) => entry.content !== entry.original)
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
      const dirty = entry ? entry.content !== entry.original : false
      fileEditorState[path] = { dirty }
    }
    return {
      version: 3,
      selectedPath,
      pinnedPaths: (pinnedPaths || []).slice(0, PIN_LIMIT),
      selectionTrail: (selectionTrail || []).slice(-10),
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
        localStorage.setItem(wsKey(projectId), JSON.stringify(buildWorkspaceState()))
      } catch {}
    },
    [buildWorkspaceState],
  )

  const notificationTimersRef = useRef<Record<string, number>>({})

  const clearNotificationTimer = useCallback((id: string) => {
    const t = notificationTimersRef.current[id]
    if (t != null) window.clearTimeout(t)
    delete notificationTimersRef.current[id]
  }, [])

  const dismissNotification = useCallback(
    (id: string) => {
      clearNotificationTimer(id)
      setNotifications((prev) => prev.filter((n) => n.id !== id))
    },
    [clearNotificationTimer],
  )

  useEffect(() => {
    return () => {
      Object.values(notificationTimersRef.current).forEach((t) => window.clearTimeout(t))
      notificationTimersRef.current = {}
    }
  }, [])

  const pushNotification = useCallback(
    (kind: NotificationKind, message: string) => {
      const text = message.trim()
      if (!text) return
      const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`
      const ttlMs = kind === 'error' ? 15_000 : 8_000

      setNotifications((prev) => {
        const next = [...prev.slice(-4), { id, kind, text }]
        const nextIds = new Set(next.map((n) => n.id))
        prev.forEach((n) => {
          if (!nextIds.has(n.id)) clearNotificationTimer(n.id)
        })
        return next
      })

      clearNotificationTimer(id)
      notificationTimersRef.current[id] = window.setTimeout(() => dismissNotification(id), ttlMs)
    },
    [clearNotificationTimer, dismissNotification]
  )

  const setErrorMessage = useCallback(
    (message: string | null) => {
      setError(message)
      if (message) pushNotification('error', message)
    },
    [pushNotification]
  )

  const notifyInfo = useCallback((message: string) => {
    pushNotification('info', message)
  }, [pushNotification])

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

    try {
      const raw = localStorage.getItem(wsKey(pid))
      const legacyRaw = raw ? null : localStorage.getItem(legacyWsKey(pid))
      const legacyRawV1 = raw || legacyRaw ? null : localStorage.getItem(legacyWsKeyV1(pid))
      const parsedRaw = raw || legacyRaw || legacyRawV1
      if (parsedRaw) {
        const parsed = JSON.parse(parsedRaw) as Partial<WorkspaceStateV3> | Partial<WorkspaceStateV2> | Partial<WorkspaceStateV1>
        const nextSelected = asStr(parsed.selectedPath) || null
        const nextPinned = asStrArr(parsed.pinnedPaths, 20).slice(0, PIN_LIMIT)
        const nextTrail = asStrArr(parsed.selectionTrail, 20).slice(-10)
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
        if ('fileEditorsByPath' in parsed && parsed.fileEditorsByPath) {
          const storedEditors = parsed.fileEditorsByPath as Record<string, { dirty?: boolean }>
          for (const path of nextOpenFilePaths) {
            nextFileEditors[path] = createFileEditorEntry(path, { dirty: Boolean(storedEditors?.[path]?.dirty) })
          }
        } else {
          for (const path of nextOpenFilePaths) {
            nextFileEditors[path] = createFileEditorEntry(path)
          }
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
    } catch {}

    resetForSelectionChange()
    setPrompt('')
    setSearchQuery('')
    setSearchResults([])
    setErrorMessage(null)

    const t = window.setTimeout(() => {
      workspaceBootingRef.current = false
    }, 0)
    return () => window.clearTimeout(t)
  }, [activeProject?.id, resetForSelectionChange, setErrorMessage])

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
        const trail = out.slice(-10)
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

  const onClearSelection = useCallback(() => {
    setSelection(null, { pushHistory: true })
  }, [setSelection])

  const isSelectedPinned = useMemo(() => {
    if (!selectedPath) return false
    return pinnedPaths.includes(selectedPath)
  }, [pinnedPaths, selectedPath])

  const togglePinPath = useCallback((path: string) => {
    const p = String(path || '').trim()
    if (!p) return
    setPinnedPaths((prev) => {
      if (prev.includes(p)) return prev.filter((x) => x !== p)
      if (prev.length >= PIN_LIMIT) {
        // Drop oldest pinned
        return [...prev.slice(1), p]
      }
      return [...prev, p]
    })
  }, [])

  const togglePinSelected = useCallback(() => {
    if (!selectedPath) return
    togglePinPath(selectedPath)
  }, [selectedPath, togglePinPath])

  const unpinPath = useCallback((path: string) => {
    const p = String(path || '').trim()
    if (!p) return
    setPinnedPaths((prev) => prev.filter((x) => x !== p))
  }, [])

  const clearPins = useCallback(() => setPinnedPaths([]), [])

  const canGoBack = backStack.length > 0
  const canGoForward = forwardStack.length > 0

  const goBack = useCallback(() => {
    const b = backStackRef.current || []
    if (b.length === 0) return
    const current = selectedPathRef.current
    const prev = b[b.length - 1]

    const nextBack = b.slice(0, -1)
    backStackRef.current = nextBack
    setBackStack(nextBack)

    if (current) {
      const nextFwd = [current, ...(forwardStackRef.current || [])].slice(0, 200)
      forwardStackRef.current = nextFwd
      setForwardStack(nextFwd)
    }

    // trail
    if (prev) {
      const t0 = selectionTrailRef.current || []
      const filtered = t0.filter((p) => p !== prev)
      const t1 = [...filtered, prev].slice(-10)
      selectionTrailRef.current = t1
      setSelectionTrail(t1)
    }

    selectedPathRef.current = prev
    setSelectedPath(prev)
    resetForSelectionChange()
  }, [resetForSelectionChange])

  const goForward = useCallback(() => {
    const f = forwardStackRef.current || []
    if (f.length === 0) return
    const current = selectedPathRef.current
    const next = f[0]

    const nextFwd = f.slice(1)
    forwardStackRef.current = nextFwd
    setForwardStack(nextFwd)

    if (current) {
      const nextBack = [...(backStackRef.current || []), current].slice(-200)
      backStackRef.current = nextBack
      setBackStack(nextBack)
    }

    // trail
    if (next) {
      const t0 = selectionTrailRef.current || []
      const filtered = t0.filter((p) => p !== next)
      const t1 = [...filtered, next].slice(-10)
      selectionTrailRef.current = t1
      setSelectionTrail(t1)
    }

    selectedPathRef.current = next
    setSelectedPath(next)
    resetForSelectionChange()
  }, [resetForSelectionChange])

  const onGraphBackgroundTap = useCallback(() => {
    if (selectedPath) onClearSelection()
  }, [onClearSelection, selectedPath])

  const projectsQuery = useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: listProjects,
    initialData: [],
  })

  const runsQuery = useQuery<RunRecord[]>({
    queryKey: ['runs', activeProject?.id],
    enabled: !!activeProject,
    queryFn: async () => {
      if (!activeProject) return [] as RunRecord[]
      return listRuns(activeProject.id)
    },
    initialData: [],
  })

  const graphQueryKey = useMemo(
    () => {
      const pid = activeProject?.id ?? null
      if (!pid) return ['graph', null]
      if (graphMode === 'local') return ['graph', pid, 'local', selectedPath ?? null, graphHops, graphLocalMax]
      if (graphMode === 'limit') return ['graph', pid, 'limit', graphLimitN]
      if (graphMode === 'full') return ['graph', pid, 'full']
      return ['graph', pid, graphMode]
    },
    [activeProject?.id, graphMode, graphHops, graphLocalMax, graphLimitN, selectedPath],
  )

  const graphQuery = useQuery<GraphData | null>({
    queryKey: graphQueryKey,
    enabled: !!activeProject && (graphMode !== 'local' || !!selectedPath),
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
    queryKey: ['node', activeProject?.id, selectedPath],
    enabled: !!activeProject && !!selectedPath,
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
        err = err ? `${err}\n${e2}` : e2
      }

      if (err) setErrorMessage(err)
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
    setPendingActivePath(null)
    setPendingReloadPath(null)
    setConfirmOpen(false)
    setConfirmReason(null)
    setPendingView(null)
  }, [activeProject?.id, persistWorkspace, setErrorMessage])

  const projects = projectsQuery.data ?? []
  const runs = runsQuery.data ?? []
  const graph = graphQuery.data ?? null

  const filesQuery = useQuery<{ files: ProjectFileItem[]; meta: any }>({
    queryKey: ['files', activeProject?.id],
    enabled: !!activeProject,
    queryFn: async () => {
      if (!activeProject) return { files: [], meta: { total: 0, returned: 0, truncated: false, limit: 0 } }
      return listProjectFiles(activeProject.id)
    },
    initialData: { files: [], meta: { total: 0, returned: 0, truncated: false, limit: 0 } },
    staleTime: 30_000,
  })

  const [docs, setDocs] = useState<ProjectDocs | null>(null)
  const [docsBusy, setDocsBusy] = useState(false)
  const [docsBuildBusy, setDocsBuildBusy] = useState(false)
  const [docsBuildError, setDocsBuildError] = useState<string | null>(null)

  useEffect(() => {
    setDocs(null)
    setDocsBuildError(null)
  }, [activeProject?.id])

  useEffect(() => {
    setOpenFilePaths([])
    setFileEditorsByPath({})
    setActiveFilePath(null)
    setPendingClosePath(null)
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
      const d = await buildProjectDocs(activeProject.id, { background: true, pollIntervalMs: 1200, maxAttempts: 300 })
      setDocs(d)
      setDocsBuildError(null)
      notifyInfo('Docs built')
    } catch (e: any) {
      setDocsBuildError(extractError(e))
      setErrorMessage(extractError(e))
    } finally {
      setDocsBuildBusy(false)
    }
  }, [activeProject, notifyInfo, setErrorMessage])

  const updateFileEditorEntry = useCallback((path: string, updater: (entry: FileEditorEntry) => FileEditorEntry) => {
    const p = String(path || '').trim()
    if (!p) return
    setFileEditorsByPath((prev) => {
      const current = prev[p] ?? createFileEditorEntry(p)
      const next = updater(current)
      if (next === current) return prev
      return { ...prev, [p]: next }
    })
  }, [])

  const setActiveFileContent = useCallback(
    (value: string) => {
      if (!activeFilePath) return
      updateFileEditorEntry(activeFilePath, (entry) => ({ ...entry, content: value }))
    },
    [activeFilePath, updateFileEditorEntry],
  )

  const loadFileEditor = useCallback(
    async (path: string) => {
      if (!activeProject) return
      const p = String(path || '').trim()
      if (!p) return
      updateFileEditorEntry(p, (entry) => ({ ...entry, busy: true, error: null }))
      try {
        const res: FileContent = await getFileContent(activeProject.id, p, FILE_EDITOR_MAX_CHARS)
        const content = String(res.content ?? '')
        updateFileEditorEntry(p, (entry) => ({
          ...entry,
          content,
          original: content,
          truncated: Boolean(res.truncated),
          busy: false,
          saving: false,
          error: null,
        }))
      } catch (e: any) {
        updateFileEditorEntry(p, (entry) => ({
          ...entry,
          content: '',
          original: '',
          truncated: false,
          busy: false,
          saving: false,
          error: extractError(e),
        }))
      }
    },
    [activeProject, updateFileEditorEntry],
  )

  const clearConfirm = useCallback(() => {
    setConfirmOpen(false)
    setConfirmReason(null)
    setPendingClosePath(null)
    setPendingActivePath(null)
    setPendingReloadPath(null)
    setPendingView(null)
  }, [])

  const openFileEditor = useCallback(
    async (path: string) => {
      if (!activeProject) return
      const p = String(path || '').trim()
      if (!p) return
      const activeEntry = activeFilePath ? fileEditorsByPath[activeFilePath] : null
      const activeDirty = activeEntry ? activeEntry.content !== activeEntry.original : false
      if (activeDirty && activeFilePath && p !== activeFilePath) {
        setConfirmOpen(true)
        setConfirmReason('switch-tab')
        setPendingActivePath(p)
        setPendingClosePath(null)
        setPendingView(null)
        return
      }
      setOpenFilePaths((prev) => (prev.includes(p) ? prev : [...prev, p]))
      setActiveFilePath(p)
      updateFileEditorEntry(p, (entry) => entry)
      const existingEntry = fileEditorsByPath[p]
      const shouldLoad = !existingEntry || (!existingEntry.content && !existingEntry.original && !existingEntry.busy)
      if (shouldLoad) {
        await loadFileEditor(p)
      }
    },
    [activeProject, activeFilePath, fileEditorsByPath, loadFileEditor, updateFileEditorEntry],
  )

  const openFileEditorAt = useCallback(
    async (path: string, line: number, column: number) => {
      if (!activeProject) return
      const p = String(path || '').trim()
      if (!p) return
      setPendingJump({
        path: p,
        line: Math.max(1, Math.trunc(line || 1)),
        column: Math.max(1, Math.trunc(column || 1)),
      })
      if (workspaceView !== 'editor') {
        setWorkspaceViewState('editor')
      }
      await openFileEditor(p)
    },
    [activeProject, openFileEditor, workspaceView],
  )

  const clearPendingJump = useCallback(() => {
    setPendingJump(null)
  }, [])

  const requestReloadFileEditor = useCallback(async () => {
    if (!activeFilePath) return
    const activeEntry = fileEditorsByPath[activeFilePath]
    const activeDirty = activeEntry ? activeEntry.content !== activeEntry.original : false
    if (activeDirty) {
      setConfirmOpen(true)
      setConfirmReason('reload-file')
      setPendingReloadPath(activeFilePath)
      setPendingClosePath(null)
      setPendingActivePath(null)
      setPendingView(null)
      return
    }
    await loadFileEditor(activeFilePath)
  }, [activeFilePath, fileEditorsByPath, loadFileEditor])

  const saveFileEditorPath = useCallback(async (path: string): Promise<boolean> => {
    if (!activeProject) return false
    const p = String(path || '').trim()
    if (!p) return false
    const entry = fileEditorsByPath[p]
    if (!entry) return false
    updateFileEditorEntry(p, (current) => ({ ...current, saving: true, error: null }))
    try {
      const res: FileSaveResult = await updateFileContent(activeProject.id, p, entry.content)
      if (res?.saved) {
        updateFileEditorEntry(p, (current) => ({
          ...current,
          original: current.content,
          truncated: false,
        }))
        notifyInfo('File saved')
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ['graph', activeProject.id] }),
          queryClient.invalidateQueries({ queryKey: ['node', activeProject.id] }),
          queryClient.invalidateQueries({ queryKey: ['files', activeProject.id] }),
        ])
        return true
      }
    } catch (e: any) {
      updateFileEditorEntry(p, (current) => ({ ...current, error: extractError(e) }))
    } finally {
      updateFileEditorEntry(p, (current) => ({ ...current, saving: false }))
    }
    return false
  }, [activeProject, fileEditorsByPath, notifyInfo, queryClient, updateFileEditorEntry])

  const saveFileEditor = useCallback(async (): Promise<boolean> => {
    if (!activeFilePath) return false
    return saveFileEditorPath(activeFilePath)
  }, [activeFilePath, saveFileEditorPath])

  const confirmSave = useCallback(async () => {
    const targetPath = pendingClosePath ?? activeFilePath
    const targetEntry = targetPath ? fileEditorsByPath[targetPath] : null
    if (targetEntry?.saving || targetEntry?.busy) return
    const saved = targetPath ? await saveFileEditorPath(targetPath) : false
    if (!saved) return
    if (pendingClosePath) {
      setOpenFilePaths((prev) => {
        if (!prev.includes(pendingClosePath)) return prev
        const next = prev.filter((item) => item !== pendingClosePath)
        if (activeFilePath === pendingClosePath) {
          const idx = prev.indexOf(pendingClosePath)
          const nextActive = next[idx - 1] ?? next[idx] ?? null
          setActiveFilePath(nextActive)
        }
        return next
      })
      setFileEditorsByPath((prev) => {
        if (!(pendingClosePath in prev)) return prev
        const next = { ...prev }
        delete next[pendingClosePath]
        return next
      })
    } else if (pendingActivePath) {
      await openFileEditor(pendingActivePath)
    } else if (pendingView) {
      setWorkspaceViewState(pendingView)
    }
    clearConfirm()
  }, [
    clearConfirm,
    openFileEditor,
    pendingActivePath,
    pendingClosePath,
    pendingView,
    saveFileEditorPath,
    activeFilePath,
    fileEditorsByPath,
  ])

  const confirmDiscard = useCallback(async () => {
    if (confirmReason === 'reload-file') {
      const targetPath = pendingReloadPath ?? activeFilePath
      const targetEntry = targetPath ? fileEditorsByPath[targetPath] : null
      if (targetEntry?.saving || targetEntry?.busy) return
      if (targetPath) {
        await loadFileEditor(targetPath)
      }
      setPendingReloadPath(null)
      clearConfirm()
      return
    }
    const targetPath = pendingClosePath ?? activeFilePath
    const targetEntry = targetPath ? fileEditorsByPath[targetPath] : null
    if (targetEntry?.saving || targetEntry?.busy) return
    if (targetPath) {
      updateFileEditorEntry(targetPath, (entry) => {
        if (entry.content === entry.original) return entry
        return { ...entry, content: entry.original, error: null }
      })
    }
    if (pendingClosePath) {
      setOpenFilePaths((prev) => {
        if (!prev.includes(pendingClosePath)) return prev
        const next = prev.filter((item) => item !== pendingClosePath)
        if (activeFilePath === pendingClosePath) {
          const idx = prev.indexOf(pendingClosePath)
          const nextActive = next[idx - 1] ?? next[idx] ?? null
          setActiveFilePath(nextActive)
        }
        return next
      })
      setFileEditorsByPath((prev) => {
        if (!(pendingClosePath in prev)) return prev
        const next = { ...prev }
        delete next[pendingClosePath]
        return next
      })
    } else if (pendingActivePath) {
      await openFileEditor(pendingActivePath)
    } else if (pendingView) {
      setWorkspaceViewState(pendingView)
    }
    clearConfirm()
  }, [
    clearConfirm,
    confirmReason,
    fileEditorsByPath,
    loadFileEditor,
    openFileEditor,
    pendingActivePath,
    pendingClosePath,
    pendingReloadPath,
    pendingView,
    activeFilePath,
    updateFileEditorEntry,
  ])

  const confirmCancel = useCallback(() => {
    const activeEntry = activeFilePath ? fileEditorsByPath[activeFilePath] : null
    if (activeEntry?.saving || activeEntry?.busy) return
    clearConfirm()
  }, [activeFilePath, clearConfirm, fileEditorsByPath])

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

  const onPickProject = useCallback((p: Project) => selectProjectLocal(p), [selectProjectLocal])

  const onCreateProject = useCallback(async () => {
    await runOp(async () => {
      const name = newName.trim()
      const root = newPath.trim()
      const p = await createProject(name, root)
      selectProjectLocal(p)
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
    })
  }, [newName, newPath, queryClient, runOp, selectProjectLocal])

  const onDeleteActiveProject = useCallback(async () => {
    const pid = Number(activeProject?.id)
    if (!Number.isFinite(pid) || pid <= 0) return
    await runOp(async () => {
      await deleteProject(pid)
      try {
        localStorage.removeItem(wsKey(pid))
      } catch {}
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      const remaining = (projectsQuery.data ?? []).filter((p) => p.id !== pid)
      if (remaining.length) {
        selectProjectLocal(remaining[0])
      } else {
        clearActiveProject()
      }
    })
  }, [activeProject?.id, clearActiveProject, projectsQuery.data, queryClient, runOp, selectProjectLocal])

  const onScan = useCallback(async () => {
    if (!activeProject) return
    await runOp(async () => {
      await scanProject(activeProject.id)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['graph', activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['runs', activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['node', activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['files', activeProject.id] }),
      ])
    })
  }, [activeProject, queryClient, runOp])

  const onRefresh = useCallback(async () => {
    if (!activeProject) return
    await runOp(async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['graph', activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['runs', activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['node', activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['files', activeProject.id] }),
      ])
    })
  }, [activeProject, queryClient, runOp])

  const onCreateFile = useCallback(
    async (path: string, content?: string) => {
      if (!activeProject) return
      const p = String(path || '').trim()
      if (!p) return
      let createdPath: string | null = null
      await runOpThrow(async () => {
        const res = await createFile(activeProject.id, p, content)
        const nextPath = String(res?.path || p).trim() || p
        createdPath = nextPath
        notifyInfo('File created')
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ['files', activeProject.id] }),
          queryClient.invalidateQueries({ queryKey: ['graph', activeProject.id] }),
          queryClient.invalidateQueries({ queryKey: ['node', activeProject.id] }),
        ])
      })
      if (createdPath) {
        setSelection(createdPath, { pushHistory: true })
      }
    },
    [activeProject, notifyInfo, queryClient, runOpThrow, setSelection],
  )

  const onRenameFile = useCallback(
    async (path: string, newPath: string) => {
      if (!activeProject) return
      const oldPath = String(path || '').trim()
      const nextRaw = String(newPath || '').trim()
      if (!oldPath || !nextRaw || oldPath === nextRaw) return
      await runOpThrow(async () => {
        const res = await renameFile(activeProject.id, oldPath, nextRaw)
        const nextPath = String(res?.path || nextRaw).trim() || nextRaw
        setOpenFilePaths((prev) => prev.map((item) => (item === oldPath ? nextPath : item)))
        setFileEditorsByPath((prev) => {
          if (!(oldPath in prev)) return prev
          const next = { ...prev }
          const entry = next[oldPath]
          delete next[oldPath]
          next[nextPath] = { ...entry, path: nextPath }
          return next
        })
        setPinnedPaths((prev) => prev.map((item) => (item === oldPath ? nextPath : item)))
        setActiveFilePath((prev) => (prev === oldPath ? nextPath : prev))
        if (selectedPathRef.current === oldPath) {
          setSelection(nextPath, { pushHistory: false })
        }
        notifyInfo('File renamed')
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ['files', activeProject.id] }),
          queryClient.invalidateQueries({ queryKey: ['graph', activeProject.id] }),
          queryClient.invalidateQueries({ queryKey: ['node', activeProject.id] }),
        ])
      })
    },
    [activeProject, notifyInfo, queryClient, runOpThrow, setSelection],
  )

  const onDeleteFile = useCallback(
    async (path: string) => {
      if (!activeProject) return
      const p = String(path || '').trim()
      if (!p) return
      await runOpThrow(async () => {
        await deleteFile(activeProject.id, p)
        setOpenFilePaths((prev) => prev.filter((item) => item !== p))
        setFileEditorsByPath((prev) => {
          if (!(p in prev)) return prev
          const next = { ...prev }
          delete next[p]
          return next
        })
        setPinnedPaths((prev) => prev.filter((item) => item !== p))
        setActiveFilePath((prev) => (prev === p ? null : prev))
        if (selectedPathRef.current === p) {
          setSelection(null, { pushHistory: false })
        }
        notifyInfo('File deleted')
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ['files', activeProject.id] }),
          queryClient.invalidateQueries({ queryKey: ['graph', activeProject.id] }),
          queryClient.invalidateQueries({ queryKey: ['node', activeProject.id] }),
        ])
      })
    },
    [activeProject, notifyInfo, queryClient, runOpThrow, setSelection],
  )

  const onDeleteRun = useCallback(
    async (runId: number) => {
      const pid = Number(activeProject?.id)
      if (!Number.isFinite(pid) || pid <= 0 || !Number.isFinite(runId)) return
      await runOp(async () => {
        await deleteRun(pid, runId)
        if (runResult?.run_id === runId) {
          setRunResult(null)
          setFullPatch(null)
        }
        await queryClient.invalidateQueries({ queryKey: ['runs', pid] })
      })
    },
    [activeProject?.id, queryClient, runOp, runResult?.run_id]
  )

  const onLoadFullGraph = useCallback(() => {
    if (!activeProject) return
    setGraphMode('full')
    setErrorMessage(null)
  }, [activeProject, setErrorMessage])

  const onNavigatePath = useCallback(
    (path: string) => {
      if (!activeProject) return
      const p = String(path || '').trim()
      if (!p) return
      setSelection(p, { pushHistory: true })
    },
    [activeProject, setSelection],
  )

  const onSelectNodePath = useCallback(
    (path: string) => {
      if (!activeProject) return
      const p = String(path || '').trim()
      if (!p) return
      setSelection(p, { pushHistory: true })
      const hasGraph = Boolean(graph?.nodes && Array.isArray(graph.nodes) && graph.nodes.length > 0)
      const inCurrentGraph = hasGraph ? Boolean(graph?.nodes?.some((n: any) => n?.path === p || n?.id === p)) : true

      if (!inCurrentGraph && graphMode !== 'local') {
        setGraphMode('local')
        notifyInfo('Switched to local graph to reveal selection')
      }
    },
    [activeProject, graph?.nodes, graphMode, notifyInfo, setSelection]
  )

  const onGraphNodeTap = useCallback(
    (path: string) => {
      if (!activeProject) return
      setSelection(path, { pushHistory: true })
    },
    [activeProject, setSelection]
  )

  const onLoadFullPatch = useCallback(async () => {
    if (!activeProject) return
    const runId = Number(runResult?.run_id)
    if (!Number.isFinite(runId) || runId <= 0) return

    setPatchBusy(true)
    setErrorMessage(null)
    try {
      const r = await getRunPatch(activeProject.id, runId)
      const txt = typeof r?.patch_unified_diff === 'string' ? r.patch_unified_diff : ''
      setFullPatch(txt)
    } catch (e: any) {
      setErrorMessage(extractError(e))
    } finally {
      setPatchBusy(false)
    }
  }, [activeProject, runResult])

  const onApplyRunPatch = useCallback(async () => {
    if (!activeProject) return
    const runId = Number(runResult?.run_id)
    if (!Number.isFinite(runId) || runId <= 0) return

    await runOp(async () => {
      const res = await applyRunPatch(activeProject.id, runId)
      setRunResult((prev) => {
        if (!prev || prev.run_id !== runId) return prev
        return {
          ...prev,
          applied: res.applied ?? undefined,
        }
      })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['graph', activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['node', activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['files', activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['runs', activeProject.id] }),
      ])
    })
  }, [activeProject, queryClient, runOp, runResult?.run_id])

  const onLoadRun = useCallback(
    async (runId: number) => {
      if (!activeProject) return
      if (!Number.isFinite(runId) || runId <= 0) return

      setRunLoadBusy(true)
      setErrorMessage(null)
      try {
        const r = await getRun(activeProject.id, runId)
        const tp = typeof r.target_path === 'string' ? r.target_path.trim() : ''

        if (tp) setSelection(tp, { pushHistory: true })

        setRunResult({
          run_id: r.id,
          mode: r.mode,
          depth: r.depth ?? undefined,
          dep_mode: r.dep_mode ?? undefined,
          retrieval: r.retrieval ?? undefined,
          retrieval_settings: r.retrieval_settings ?? undefined,
          apply_patch: r.apply_patch ?? undefined,
          result: r.result,
          applied: r.applied ?? undefined,
          warning: r.warning ?? undefined,
        })
        setFullPatch(null)
      } catch (e: any) {
        setErrorMessage(extractError(e))
      } finally {
        setRunLoadBusy(false)
      }
    },
    [activeProject, setSelection]
  )

  const buildRunBody = useCallback(
    (extra?: Partial<RunTaskBody>): RunTaskBody | null => {
      if (!selectedPath) return null
      const clampedPackMaxFiles = clampInt(packMaxFiles, 1, 80)
      const clampedPackMaxCharsPerFile = clampInt(packMaxCharsPerFile, 1, 200_000)
      let clampedPackMaxTotalChars = clampInt(packMaxTotalChars, 1, 2_000_000)
      if (clampedPackMaxTotalChars < clampedPackMaxCharsPerFile) {
        clampedPackMaxTotalChars = clampedPackMaxCharsPerFile
      }
      if (clampedPackMaxFiles !== packMaxFiles) setPackMaxFiles(clampedPackMaxFiles)
      if (clampedPackMaxCharsPerFile !== packMaxCharsPerFile) setPackMaxCharsPerFile(clampedPackMaxCharsPerFile)
      if (clampedPackMaxTotalChars !== packMaxTotalChars) setPackMaxTotalChars(clampedPackMaxTotalChars)

      const clampedAgenticMaxCalls = clampInt(agenticMaxCalls, 1, 100)
      const clampedAgenticMaxFileChars = clampInt(agenticMaxFileChars, 1, 200_000)
      const clampedAgenticMaxTotalToolOutputChars = clampInt(agenticMaxTotalToolOutputChars, 1, 2_000_000)
      if (clampedAgenticMaxCalls !== agenticMaxCalls) setAgenticMaxCalls(clampedAgenticMaxCalls)
      if (clampedAgenticMaxFileChars !== agenticMaxFileChars) setAgenticMaxFileChars(clampedAgenticMaxFileChars)
      if (clampedAgenticMaxTotalToolOutputChars !== agenticMaxTotalToolOutputChars) {
        setAgenticMaxTotalToolOutputChars(clampedAgenticMaxTotalToolOutputChars)
      }

      const body: RunTaskBody = {
        target_path: selectedPath,
        prompt,
        apply_patch: applyPatch,
        agentic: retrievalMode === 'agentic',
      }
      if (retrievalMode === 'agentic') {
        body.agentic_max_calls = clampedAgenticMaxCalls
        body.agentic_max_file_chars = clampedAgenticMaxFileChars
        body.agentic_max_total_tool_output_chars = clampedAgenticMaxTotalToolOutputChars
        body.agentic_temperature = agenticTemperature
      } else {
        body.pack_max_files = clampedPackMaxFiles
        body.pack_max_chars_per_file = clampedPackMaxCharsPerFile
        body.pack_max_total_chars = clampedPackMaxTotalChars
      }
      if (mode !== 'auto') {
        body.mode = mode
        body.depth = depth
        if (retrievalMode === 'pack') body.dep_mode = depMode
      }

      return extra ? { ...body, ...extra } : body
    },
    [
      agenticMaxCalls,
      agenticMaxFileChars,
      agenticMaxTotalToolOutputChars,
      agenticTemperature,
      applyPatch,
      depth,
      depMode,
      mode,
      packMaxCharsPerFile,
      packMaxFiles,
      packMaxTotalChars,
      prompt,
      retrievalMode,
      selectedPath,
      setAgenticMaxCalls,
      setAgenticMaxFileChars,
      setAgenticMaxTotalToolOutputChars,
      setPackMaxCharsPerFile,
      setPackMaxFiles,
      setPackMaxTotalChars,
    ]
  )

  const onRun = useCallback(async () => {
    if (!activeProject || !selectedPath) return

    await runOp(async () => {
      setRunResult(null)
      setFullPatch(null)

      const body = buildRunBody()
      if (!body) return
      const res = await runTask(activeProject.id, body)
      setRunResult(res)

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['graph', activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['runs', activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['node', activeProject.id] }),
      ])
    })
  }, [
    activeProject,
    selectedPath,
    runOp,
    buildRunBody,
    queryClient,
  ])

  const onRunWithExpandedContext = useCallback(async () => {
    if (!activeProject || !selectedPath) return

    await runOp(async () => {
      setRunResult(null)
      setFullPatch(null)

      const body = buildRunBody({ allow_out_of_context_patch: true })
      if (!body) return
      const res = await runTask(activeProject.id, body)
      setRunResult(res)

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['graph', activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['runs', activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['node', activeProject.id] }),
      ])
    })
  }, [activeProject, selectedPath, runOp, buildRunBody, queryClient])

  const onSearchNodes = useCallback(
    async (query: string) => {
      if (!activeProject) return
      setSearchQuery(query)
      setSemanticSearchFallbackUsed(false)
      if (!query.trim()) {
        searchSeqRef.current++
        setSearchBusy(false)
        setSearchResults([])
        setSearchSemanticResults([])
        return
      }
      const seq = ++searchSeqRef.current
      setSearchBusy(true)
      try {
        if (semanticSearchEnabled) {
          const res = await searchProjectSemantic(activeProject.id, query, 30)
          if (searchSeqRef.current !== seq) return
          const semanticResults = res.results ?? []
          if (semanticResults.length === 0) {
            const fallbackRes = await searchNodes(activeProject.id, query, 30)
            if (searchSeqRef.current !== seq) return
            setSearchResults(fallbackRes)
            setSearchSemanticResults([])
            setSemanticSearchFallbackUsed(true)
            notifyInfo('Semantic search returned no results — showing path search instead.')
          } else {
            setSearchSemanticResults(semanticResults)
            setSearchResults([])
          }
          if (searchSeqRef.current !== seq) return
          setSemanticSearchUnavailableReason(null)
        } else {
          const res = await searchNodes(activeProject.id, query, 30)
          if (searchSeqRef.current !== seq) return
          setSearchResults(res)
          setSearchSemanticResults([])
        }
      } catch (e: any) {
        if (searchSeqRef.current !== seq) return
        const reason = semanticSearchEnabled ? getSemanticSearchErrorReason(e) : null
        if (semanticSearchEnabled && reason) {
          setSemanticSearchEnabled(false)
          setSemanticSearchUnavailableReason(reason)
          if (reason === 'no_embeddings') {
            notifyInfo('Project embeddings are missing — run Scan with embeddings enabled.')
          }
          try {
            const res = await searchNodes(activeProject.id, query, 30)
            if (searchSeqRef.current !== seq) return
            setSearchResults(res)
            setSearchSemanticResults([])
            notifyInfo('Semantic search is unavailable — using standard search.')
          } catch (fallbackError: any) {
            setErrorMessage(extractError(fallbackError))
          }
        } else {
          setErrorMessage(extractError(e))
        }
      } finally {
        if (searchSeqRef.current === seq) setSearchBusy(false)
      }
    },
    [activeProject, notifyInfo, semanticSearchEnabled, setErrorMessage]
  )

  const onSearchText = useCallback(
    async (queryInput: string) => {
      if (!activeProject) return
      const query = String(queryInput || '').trim()
      setTextSearchQuery(query)
      if (!query) {
        textSearchSeqRef.current++
        setTextSearchBusy(false)
        setTextSearchResults([])
        setTextSearchMeta(null)
        setTextSearchError(null)
        return
      }
      const seq = ++textSearchSeqRef.current
      setTextSearchBusy(true)
      setTextSearchError(null)
      try {
        const res = await searchProjectText(activeProject.id, query, {
          prefix: textSearchPrefix.trim() || undefined,
          case_sensitive: textSearchCaseSensitive,
        })
        if (textSearchSeqRef.current !== seq) return
        setTextSearchResults(res.matches || [])
        setTextSearchMeta(res.meta || null)
      } catch (e: any) {
        if (textSearchSeqRef.current !== seq) return
        setTextSearchError(extractError(e))
      } finally {
        if (textSearchSeqRef.current === seq) setTextSearchBusy(false)
      }
    },
    [activeProject, textSearchCaseSensitive, textSearchPrefix],
  )

  const closeFileEditor = useCallback(
    (path: string) => {
      const p = String(path || '').trim()
      if (!p) return
      const entry = fileEditorsByPath[p]
      const isDirty = entry ? entry.content !== entry.original : false
      if (isDirty) {
        setConfirmOpen(true)
        setConfirmReason('close-tab')
        setPendingClosePath(p)
        setPendingActivePath(null)
        setPendingView(null)
        return
      }
      setOpenFilePaths((prev) => {
        if (!prev.includes(p)) return prev
        const next = prev.filter((item) => item !== p)
        if (activeFilePath === p) {
          const idx = prev.indexOf(p)
          const nextActive = next[idx - 1] ?? next[idx] ?? null
          setActiveFilePath(nextActive)
        }
        return next
      })
      setFileEditorsByPath((prev) => {
        if (!(p in prev)) return prev
        const next = { ...prev }
        delete next[p]
        return next
      })
    },
    [activeFilePath, fileEditorsByPath],
  )

  const setWorkspaceView = useCallback(
    (nextView: WorkspaceView) => {
      if (workspaceView === nextView) return
      const activeEntry = activeFilePath ? fileEditorsByPath[activeFilePath] : null
      const activeDirty = activeEntry ? activeEntry.content !== activeEntry.original : false
      if (activeDirty && nextView === 'graph') {
        setConfirmOpen(true)
        setConfirmReason('close-editor')
        setPendingView('graph')
        setPendingClosePath(null)
        setPendingActivePath(null)
        return
      }
      setWorkspaceViewState(nextView)
      const nextPath = selectedPathRef.current
      if (nextView === 'editor' && nextPath && nextPath !== activeFilePath) {
        void openFileEditor(nextPath)
      }
    },
    [activeFilePath, fileEditorsByPath, openFileEditor, workspaceView],
  )

  const toggleWorkspaceView = useCallback(() => {
    setWorkspaceView(workspaceView === 'graph' ? 'editor' : 'graph')
  }, [setWorkspaceView, workspaceView])

  const fileEditorOpen = workspaceView === 'editor'

  const requestFindInFile = useCallback(() => {
    setFindRequestId((value) => value + 1)
  }, [])

  const requestReplaceInFile = useCallback(() => {
    setReplaceRequestId((value) => value + 1)
  }, [])

  const requestOutlineInFile = useCallback(() => {
    setOutlineRequestId((value) => value + 1)
  }, [])

  const registerUndoRedoHandlers = useCallback(
    (handlers: { undo: () => void; redo: () => void }) => {
      undoRedoHandlersRef.current = handlers
    },
    [],
  )

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (isAnyModalOpen() && !paletteOpen) return
      const modalCount = (() => {
        try {
          const raw = String(document.body?.dataset?.csModalOpenCount ?? '').trim()
          const n = Number(raw)
          return Number.isFinite(n) ? n : 0
        } catch {
          return 0
        }
      })()

      const otherModalOpen = modalCount > (paletteOpen ? 1 : 0)

      const mod = e.ctrlKey || e.metaKey
      if (mod && !e.shiftKey && !e.altKey && (e.key === 'k' || e.key === 'K' || e.key === 'p' || e.key === 'P')) {
        if (otherModalOpen) return
        e.preventDefault()
        setPaletteOpen((v) => !v)
        return
      }

      if (mod && e.shiftKey && !e.altKey && (e.key === 'f' || e.key === 'F')) {
        if (otherModalOpen) return
        e.preventDefault()
        onFocusSearch?.()
        return
      }

      if (mod && e.shiftKey && !e.altKey && (e.key === 'g' || e.key === 'G')) {
        if (otherModalOpen) return
        e.preventDefault()
        toggleWorkspaceView()
        return
      }

      if (mod && !e.shiftKey && !e.altKey && (e.key === 'g' || e.key === 'G')) {
        if (otherModalOpen) return
        e.preventDefault()
        setGotoLineRequestId((value) => value + 1)
        return
      }

      if (mod && !e.shiftKey && !e.altKey && (e.key === 'f' || e.key === 'F')) {
        if (otherModalOpen) return
        if (!fileEditorOpen) return
        e.preventDefault()
        requestFindInFile()
        return
      }

      if (mod && !e.shiftKey && !e.altKey && (e.key === 'h' || e.key === 'H')) {
        if (otherModalOpen) return
        if (!fileEditorOpen) return
        e.preventDefault()
        requestReplaceInFile()
        return
      }

      if (mod && e.shiftKey && !e.altKey && (e.key === 'o' || e.key === 'O')) {
        if (otherModalOpen) return
        if (!fileEditorOpen) return
        e.preventDefault()
        requestOutlineInFile()
        return
      }

      if (otherModalOpen) return

      const el = e.target as HTMLElement | null
      const tag = (el?.tagName || '').toLowerCase()
      const typing =
        tag === 'input' ||
        tag === 'textarea' ||
        tag === 'select' ||
        Boolean((el as any)?.isContentEditable) ||
        Boolean(el?.closest?.('input, textarea, select, [contenteditable="true"]'))

      if (typing) return
      if (paletteOpen) return

      if (
        !otherModalOpen
        && workspaceView === 'graph'
        && graph
        && !focusGraph
        && mod
        && !e.shiftKey
        && !e.altKey
        && (e.key === 'z' || e.key === 'Z')
      ) {
        e.preventDefault()
        undoRedoHandlersRef.current?.undo?.()
        return
      }

      if (
        !otherModalOpen
        && workspaceView === 'graph'
        && graph
        && !focusGraph
        && mod
        && e.shiftKey
        && !e.altKey
        && (e.key === 'z' || e.key === 'Z')
      ) {
        e.preventDefault()
        undoRedoHandlersRef.current?.redo?.()
        return
      }

      if (mod && !e.shiftKey && !e.altKey && (e.key === 'b' || e.key === 'B')) {
        e.preventDefault()
        if (focusGraph) {
          setFocusGraph(false)
          if (!leftPanelOpen) setLeftPanelOpen(true)
          return
        }
        toggleLeftPanel()
        return
      }
      if (mod && e.altKey && (e.key === 'b' || e.key === 'B')) {
        e.preventDefault()
        if (focusGraph) {
          setFocusGraph(false)
          if (!rightPanelOpen) setRightPanelOpen(true)
          return
        }
        toggleRightPanel()
        return
      }
      if (mod && e.shiftKey && !e.altKey && (e.key === 'm' || e.key === 'M')) {
        e.preventDefault()
        toggleCompactMode()
        return
      }

      const isMac = String((navigator as any)?.platform ?? '').toLowerCase().includes('mac')
      if (e.altKey && e.key === 'ArrowLeft') {
        e.preventDefault()
        if (canGoBack) goBack()
        return
      }
      if (e.altKey && e.key === 'ArrowRight') {
        e.preventDefault()
        if (canGoForward) goForward()
        return
      }
      if (isMac && e.metaKey && e.key === '[') {
        e.preventDefault()
        if (canGoBack) goBack()
        return
      }
      if (isMac && e.metaKey && e.key === ']') {
        e.preventDefault()
        if (canGoForward) goForward()
        return
      }

      if (e.key === 'Escape') {
        if (focusGraph) return void setFocusGraph(false)
        if (selectedPath) return void onClearSelection()
        return
      }
      if (e.key === 'f' || e.key === 'F') setFocusGraph((v) => !v)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [
    canGoBack,
    canGoForward,
    paletteOpen,
    focusGraph,
    goBack,
    goForward,
    onClearSelection,
    selectedPath,
    leftPanelOpen,
    rightPanelOpen,
    setLeftPanelOpen,
    setRightPanelOpen,
    toggleLeftPanel,
    toggleRightPanel,
    toggleCompactMode,
    onFocusSearch,
    toggleWorkspaceView,
    workspaceView,
    graph,
    fileEditorOpen,
    requestFindInFile,
    requestReplaceInFile,
    requestOutlineInFile,
  ])

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
    projects,
    projectsLoading: projectsQuery.isFetching,
    activeProject,
    graph,
    projectFiles: filesQuery.data?.files ?? [],
    projectFilesMeta: filesQuery.data?.meta ?? null,
    projectFilesBusy: filesQuery.isFetching,
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
    pendingJump,
    clearPendingJump,
    runs,
    newName,
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
    setNewPath,
    setGraphMode,
    setGraphLimitN,
    graphHops,
    setGraphHops,
    graphLocalMax,
    setGraphLocalMax,

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
    setPackMaxFiles,
    setPackMaxCharsPerFile,
    setPackMaxTotalChars,
    setApplyPatch,
    setPrompt,

    notifications,
    dismissNotification,
    notifyInfo,
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
    onDeleteRun,
    onLoadFullPatch,
    onApplyRunPatch,
    onLoadRun,
    onCreateFile,
    onRenameFile,
    onDeleteFile,

    // derived
    canRun,
  }
}
