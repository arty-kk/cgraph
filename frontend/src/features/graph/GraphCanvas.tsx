// frontend/src/ui/components/GraphCanvas.tsx
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { GraphData, Project } from '@/api'
import { 
  useCytoscapeGraph, type GraphFilters, 
  type LabelMode, type NodeContextMenuPayload, 
  type GraphEditSnapshot,
  type CytoscapeGraphActions,
} from './useCytoscapeGraph'
import { Modal } from '@/shared/ui/Modal'
import { safeStorageGet, safeStorageSet } from '@/shared/lib/storage'
import {
  EyeIcon,
  SummaryIcon,
  PencilIcon,
  GraphIcon,
  UndoIcon,
  RedoIcon,
  FitIcon,
  CenterIcon,
  RelayoutIcon,
  BackIcon,
  ForwardIcon,
  ClearIcon,
  PinIcon,
  UnpinIcon,
  FocusIcon,
  SaveLayoutIcon,
  ResetLayoutIcon,
  ResetFiltersIcon,
  FilterIcon,
  LockIcon,
  NeighborsIcon,
} from './GraphCanvas.icons'
import {
  FILTER_STORAGE_KEY,
  LABELS_STORAGE_KEY,
  SPOTLIGHT_STORAGE_KEY,
  EDGE_DIR_STORAGE_KEY,
  EDGE_IN_COLOR,
  EDGE_OUT_COLOR,
  DEFAULT_FILTERS,
  pidKey,
  loadFilters,
  loadLabelMode,
  loadSpotlight,
  loadEdgeDir,
} from './GraphCanvas.storage'
import { GraphHelpModal } from './GraphCanvas.HelpModal'
import { baseName, clamp } from './GraphCanvas.helpers'

type Props = {
  graph: GraphData | null
  activeProject: Project | null
  busy: boolean
  graphMode: 'local' | 'full' | 'limit'
  selectedPath: string | null
  workspaceView: 'graph' | 'editor'
  onBackgroundTap: () => void
  onNodeTap: (path: string) => void | Promise<void>
  onScan: () => void | Promise<void>
  onRefresh: () => void | Promise<void>
  onOpenPalette: () => void
  notifyInfo: (msg: string) => void
  onQuickSummary: (path: string) => void | Promise<void>
  canQuickSummary: boolean
  quickSummaryDisabledReason?: string
  compactMode: boolean
  focusGraph: boolean
  setFocusGraph: (v: boolean) => void
  leftPanelOpen: boolean
  rightPanelOpen: boolean
  onToggleLeftPanel: () => void
  onToggleRightPanel: () => void
  onClearSelection: () => void
  canGoBack?: boolean
  canGoForward?: boolean
  onBack?: () => void
  onForward?: () => void

  selectionTrail: string[]
  onNavigatePath: (path: string) => void | Promise<void>

  pinnedPaths: string[]
  isSelectedPinned: boolean
  onTogglePinSelected: () => void | Promise<void>
  onTogglePinPath: (path: string) => void | Promise<void>
  onUnpin: (path: string) => void | Promise<void>
  onClearPins: () => void | Promise<void>
  onOpenFileEditor: (path: string) => void | Promise<void>
  onToggleWorkspaceView: () => void
  onRegisterUndoRedo?: (handlers: { undo: () => void; redo: () => void }) => void
}

export function GraphCanvas({ 
  graph,
  activeProject,
  busy,
  graphMode,
  selectedPath,
  workspaceView,
  onBackgroundTap,
  onNodeTap,
  onScan,
  onRefresh,
  onOpenPalette,
  notifyInfo,
  onQuickSummary,
  canQuickSummary,
  quickSummaryDisabledReason,
  compactMode,
  focusGraph,
  setFocusGraph,
  leftPanelOpen,
  rightPanelOpen,
  onToggleLeftPanel,
  onToggleRightPanel,
  onClearSelection,
  canGoBack = false,
  canGoForward = false,
  onBack,
  onForward,

  selectionTrail,
  onNavigatePath,

  pinnedPaths,
  isSelectedPinned,
  onTogglePinSelected,
  onTogglePinPath,
  onUnpin,
  onClearPins,
  onOpenFileEditor,
  onToggleWorkspaceView,
  onRegisterUndoRedo,
}: Props) {

  const rootRef = useRef<HTMLDivElement | null>(null)

  const uiBootingRef = useRef(false)

  const label = useCallback(
    (icon: React.ReactNode, hotkey?: string) => (
      <span className="flex items-center gap-1">
        {icon}
        {compactMode && hotkey ? (
          <span className="text-[9px] text-neutral-400">{hotkey}</span>
        ) : null}
      </span>
    ),
    [compactMode],
  )
  const btnClass =
    'shrink-0 rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold disabled:opacity-50'
  const toggleBtnClass =
    'flex h-8 w-8 items-center justify-center rounded-md border border-indigo-500/50 bg-indigo-950/60 text-indigo-100 hover:bg-indigo-900/60 disabled:opacity-50'
  const hoverRevealBlock = compactMode ? 'hidden group-hover:block' : ''
  const hoverRevealFlex = compactMode ? 'hidden group-hover:flex' : 'flex'
  const quickSummaryDisabled = !canQuickSummary
  const quickSummaryTitle = quickSummaryDisabled
    ? (quickSummaryDisabledReason || 'Quick summary unavailable')
    : 'Quick summary'
  const isQuickSummaryDisabledFor = useCallback(
    (path: string) => quickSummaryDisabled || path !== selectedPath,
    [quickSummaryDisabled, selectedPath]
  )
  const quickSummaryTitleFor = useCallback(
    (path: string) => (
      path !== selectedPath
        ? 'Select this node to load info before summarizing.'
        : quickSummaryTitle
    ),
    [quickSummaryTitle, selectedPath]
  )

  const onEscAction = useCallback(() => {
    setCtxMenu(null)
    if (focusGraph) return void setFocusGraph(false)
    if (selectedPath) return void onClearSelection()
  }, [focusGraph, onClearSelection, selectedPath, setFocusGraph])

  const actionsRef = useRef<CytoscapeGraphActions | null>(null)
  const notifyRef = useRef<(msg: string) => void>(() => {})
  useEffect(() => { notifyRef.current = notifyInfo }, [notifyInfo])

  const undoStackRef = useRef<GraphEditSnapshot[]>([])
  const redoStackRef = useRef<GraphEditSnapshot[]>([])
  const dragBeforeRef = useRef<GraphEditSnapshot | null>(null)
  const [, forceRerender] = useState(0)
  const pushUndo = (snap: GraphEditSnapshot | null) => {
    if (!snap) return
    undoStackRef.current = [...undoStackRef.current.slice(-19), snap]
    redoStackRef.current = []
    forceRerender((x) => x + 1)
  }

  const doUndo = useCallback(() => {
    const a = actionsRef.current
    if (!a) return
    const prev = undoStackRef.current.pop()
    if (!prev) return
    const cur = a.exportSnapshot()
    if (cur) redoStackRef.current = [...redoStackRef.current.slice(-19), cur]
    a.applySnapshot(prev)
    forceRerender((x) => x + 1)
    notifyRef.current?.('Undo')
  }, [])

  const doRedo = useCallback(() => {
    const a = actionsRef.current
    if (!a) return
    const next = redoStackRef.current.pop()
    if (!next) return
    const cur = a.exportSnapshot()
    if (cur) undoStackRef.current = [...undoStackRef.current.slice(-19), cur]
    a.applySnapshot(next)
    forceRerender((x) => x + 1)
    notifyRef.current?.('Redo')
  }, [])

  useEffect(() => {
    onRegisterUndoRedo?.({ undo: doUndo, redo: doRedo })
    return () => {
      onRegisterUndoRedo?.({ undo: () => {}, redo: () => {} })
    }
  }, [doRedo, doUndo, onRegisterUndoRedo])

  const layoutKey = useMemo(() => {
    const pid = activeProject?.id != null ? String(activeProject.id) : 'none'
    const localSel = graphMode === 'local' ? (selectedPath || 'none') : 'global'
    return `cs.layout.v1.${pid}.${graphMode}.${localSel}`
  }, [activeProject?.id, graphMode, selectedPath])
  const loadedLayoutKeyRef = useRef<string | null>(null)

  const projectId = activeProject?.id ?? null

  const [filters, setFilters] = useState<GraphFilters>(() => loadFilters(projectId))
  const [labelMode, setLabelMode] = useState<LabelMode>(() => loadLabelMode(projectId))
  const [spotlight, setSpotlight] = useState<boolean>(() => loadSpotlight(projectId))
  const [edgeDirColors, setEdgeDirColors] = useState<boolean>(() => loadEdgeDir(projectId))
  const isGraphActive = focusGraph || workspaceView === 'graph'

  // Load per-project UI settings when project changes (skip persistence during boot)
  useEffect(() => {
    const pid = Number(projectId)
    if (!Number.isFinite(pid) || pid <= 0) return
    uiBootingRef.current = true

    setFilters(loadFilters(pid))
    setLabelMode(loadLabelMode(pid))
    setSpotlight(loadSpotlight(pid))
    setEdgeDirColors(loadEdgeDir(pid))

    const t = window.setTimeout(() => { uiBootingRef.current = false }, 0)
    return () => window.clearTimeout(t)
  }, [projectId])

  // Persist per-project UI settings (debounced-by-react; guarded by uiBootingRef)
  useEffect(() => {
    if (uiBootingRef.current) return
    const pid = Number(projectId)
    const key = pidKey(FILTER_STORAGE_KEY, Number.isFinite(pid) && pid > 0 ? pid : null)
    safeStorageSet(key, JSON.stringify(filters))
  }, [filters, projectId])

  useEffect(() => {
    if (uiBootingRef.current) return
    const pid = Number(projectId)
    const key = pidKey(LABELS_STORAGE_KEY, Number.isFinite(pid) && pid > 0 ? pid : null)
    safeStorageSet(key, labelMode)
  }, [labelMode, projectId])

  useEffect(() => {
    if (uiBootingRef.current) return
    const pid = Number(projectId)
    const key = pidKey(SPOTLIGHT_STORAGE_KEY, Number.isFinite(pid) && pid > 0 ? pid : null)
    safeStorageSet(key, spotlight ? '1' : '0')
  }, [spotlight, projectId])

  useEffect(() => {
    if (uiBootingRef.current) return
    const pid = Number(projectId)
    const key = pidKey(EDGE_DIR_STORAGE_KEY, Number.isFinite(pid) && pid > 0 ? pid : null)
    safeStorageSet(key, edgeDirColors ? '1' : '0')
  }, [edgeDirColors, projectId])

  const [panelOpen, setPanelOpen] = useState(false)
  const [neighborsOpen, setNeighborsOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)

  const panelRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!panelOpen) return
    const onDown = (e: MouseEvent) => {
      const el = e.target as Node | null
      if (!el) return
      if (panelRef.current && panelRef.current.contains(el)) return
      setPanelOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [panelOpen])

  const neighbors = useMemo(() => {
    const inSet = new Set<string>()
    const outSet = new Set<string>()
    if (!graph || !selectedPath) return { inbound: [] as string[], outbound: [] as string[] }

    const keyToPath = new Map<string, string>()
    for (const n of graph.nodes || []) {
      const id = typeof (n as any)?.id === 'string' ? String((n as any).id) : ''
      const path = typeof (n as any)?.path === 'string' ? String((n as any).path) : ''
      if (path) keyToPath.set(path, path)
      if (id && path) keyToPath.set(id, path)
      if (id && !keyToPath.has(id)) keyToPath.set(id, id)
    }

    const selNode =
      (graph.nodes || []).find((n: any) => n?.path === selectedPath || n?.id === selectedPath) ?? null
    const selId = selNode && typeof (selNode as any).id === 'string' ? String((selNode as any).id) : null

    const isSel = (k: string) => k === selectedPath || (selId != null && k === selId)
    const toPath = (k: string) => keyToPath.get(k) || k

    for (const e of graph.edges || []) {
      const s = typeof (e as any)?.source === 'string' ? String((e as any).source) : ''
      const t = typeof (e as any)?.target === 'string' ? String((e as any).target) : ''
      if (!s || !t) continue
      if (isSel(t)) inSet.add(toPath(s))
      if (isSel(s)) outSet.add(toPath(t))
    }

    const inbound = Array.from(inSet).filter(Boolean).sort()
    const outbound = Array.from(outSet).filter(Boolean).sort()
    return { inbound, outbound }
  }, [graph, selectedPath])

  useEffect(() => {
    setNeighborsOpen(false)
  }, [selectedPath])


  const [ctxMenu, setCtxMenu] = useState<null | { path: string; x: number; y: number }>(null)
  const [fileButtonPos, setFileButtonPos] = useState<null | { x: number; y: number }>(null)
  const ctxMenuRef = useRef<HTMLDivElement | null>(null)
  const fileButtonsRef = useRef<HTMLDivElement | null>(null)
  const fileButtonsSizeRef = useRef({ width: 0, height: 0 })

  useEffect(() => {
    if (!ctxMenu) return
    const onDown = (e: MouseEvent) => {
      const el = e.target as Node | null
      if (!el) return
      if (ctxMenuRef.current && ctxMenuRef.current.contains(el)) return
      setCtxMenu(null)
    }
    document.addEventListener('mousedown', onDown, true)
    return () => document.removeEventListener('mousedown', onDown, true)
  }, [ctxMenu])

  useEffect(() => {
    if (!ctxMenu) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.preventDefault()
      e.stopImmediatePropagation()
      setCtxMenu(null)
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [ctxMenu])

  useEffect(() => {
    if (!ctxMenu) return
    const t = window.setTimeout(() => {
      const root = rootRef.current
      const menu = ctxMenuRef.current
      if (!root || !menu) return

      const pad = 12
      const rootRect = root.getBoundingClientRect()
      const menuRect = menu.getBoundingClientRect()

      // x/y are in the same coordinate space as the graph canvas (absolute inside root)
      const maxX = Math.max(pad, rootRect.width - menuRect.width - pad)
      const maxY = Math.max(pad, rootRect.height - menuRect.height - pad)

      const nextX = clamp(ctxMenu.x, pad, maxX)
      const nextY = clamp(ctxMenu.y, pad, maxY)

      if (nextX !== ctxMenu.x || nextY !== ctxMenu.y) {
        setCtxMenu((prev) => (prev ? { ...prev, x: nextX, y: nextY } : prev))
      }
    }, 0)
    return () => window.clearTimeout(t)
  }, [ctxMenu])

  const openNodeMenu = (p: NodeContextMenuPayload) => {
    if (!p.path) return
    setCtxMenu({ path: p.path, x: p.x, y: p.y })
  }

  const goTo = async (path: string) => {
    await Promise.resolve(onNavigatePath(path))
    requestAnimationFrame(() => actionsRef.current?.centerPath(path))
  }

  const handleBackgroundTap = () => {
    setCtxMenu(null)
    onBackgroundTap()
  }

  const handleNodeTap = (path: string) => {
    setCtxMenu(null)
    return onNodeTap(path)
  }

  const handleNodeDoubleTap = (path: string) => {
    setCtxMenu(null)
    return onOpenFileEditor(path)
  }

  const { containerRef, stats, actions, instanceId } = useCytoscapeGraph({
    graph,
    filters,
    selectedPath,
    onBackgroundTap: handleBackgroundTap,
    onNodeTap: handleNodeTap,
    onNodeDoubleTap: handleNodeDoubleTap,
    onNodeContextMenu: openNodeMenu,
    //enableStarburst: !focusGraph,
    enableStarburst: true,
    onEditEvent: (ev) => {
      if (!focusGraph) return
      if (ev.kind === 'dragstart') {
        dragBeforeRef.current = actionsRef.current?.exportSnapshot?.() ?? null
      }
      if (ev.kind === 'dragend') {
        if (dragBeforeRef.current) pushUndo(dragBeforeRef.current)
        dragBeforeRef.current = null
      }
    },
    spotlight,
    labelMode,
    pinnedPaths,
    edgeDirectionHighlight: {
      enabled: edgeDirColors,
      inColor: EDGE_IN_COLOR,
      outColor: EDGE_OUT_COLOR,
    },
  })

  useEffect(() => {
    undoStackRef.current = []
    redoStackRef.current = []
    dragBeforeRef.current = null
    forceRerender((x) => x + 1)
  }, [
    activeProject?.id,
    instanceId,
    graph ? 1 : 0,
  ])

  useEffect(() => {
    actionsRef.current = actions
  }, [actions])

  useEffect(() => {
    const a = actionsRef.current as any
    if (!a?.resize) return
    let raf1 = 0
    let raf2 = 0
    raf1 = window.requestAnimationFrame(() => a.resize())
    raf2 = window.requestAnimationFrame(() => a.resize())
    return () => {
      if (raf1) window.cancelAnimationFrame(raf1)
      if (raf2) window.cancelAnimationFrame(raf2)
    }
  }, [instanceId, leftPanelOpen, rightPanelOpen, focusGraph])

  const meta = useMemo(() => graph?.meta ?? {}, [graph])

  const returnedNodes = useMemo(() => {
    const fromMeta = Number(meta?.returned_nodes)
    if (Number.isFinite(fromMeta)) return fromMeta
    if (!graph) return 0
    return graph.nodes.length
  }, [graph, meta?.returned_nodes])

  const returnedEdges = useMemo(() => {
    const fromMeta = Number(meta?.returned_edges)
    if (Number.isFinite(fromMeta)) return fromMeta
    if (!graph) return 0
    return graph.edges.length
  }, [graph, meta?.returned_edges])

  const totalNodes = useMemo(() => {
    const fromMeta = Number(meta?.total_nodes)
    if (Number.isFinite(fromMeta)) return fromMeta
    return returnedNodes || null
  }, [meta?.total_nodes, returnedNodes])

  const totalEdges = useMemo(() => {
    const fromMeta = Number(meta?.total_edges)
    if (Number.isFinite(fromMeta)) return fromMeta
    return returnedEdges || null
  }, [meta?.total_edges, returnedEdges])

  const limitNodes = useMemo(() => {
    const fromMeta = Number(meta?.limit_nodes)
    return Number.isFinite(fromMeta) && fromMeta > 0 ? fromMeta : null
  }, [meta?.limit_nodes])

  const limitedMode = useMemo(() => {
    return (Number(limitNodes ?? 0) > 0) || graphMode === 'limit'
  }, [graphMode, limitNodes])

  useEffect(() => {
    if (!graph || !activeProject) return
    const applyKey = `${layoutKey}::${instanceId}`
    if (loadedLayoutKeyRef.current === applyKey) return
    const has = Boolean(safeStorageGet(layoutKey))
    if (!has) {
      loadedLayoutKeyRef.current = applyKey
      return
    }
    actions.loadLayout(layoutKey, { onApplied: () => notifyInfo('Layout loaded') })
    loadedLayoutKeyRef.current = applyKey
  }, [actions, activeProject, graph, instanceId, layoutKey, notifyInfo])

  const saveLayout = () => {
    const a = actionsRef.current
    if (!a) return
    const ok = a.saveLayout(layoutKey)
    notifyRef.current(ok ? 'Layout saved' : 'Layout save failed')
  }
  const resetLayout = () => {
    const a = actionsRef.current
    if (!a) return
    pushUndo(a.exportSnapshot())
    a.clearLayout(layoutKey)
    a.relayout()
    notifyRef.current('Layout reset')
  }

  const maxRisk = useMemo(() => {
    if (!graph?.nodes?.length) return 0
    return graph.nodes.reduce((acc, n) => Math.max(acc, Number(n.risk ?? 0)), 0)
  }, [graph])

  const riskSliderMax = Math.max(1, Math.ceil(maxRisk))
  const riskStep = riskSliderMax > 50 ? 1 : 0.1

  const riskQuantiles = useMemo(() => {
    const arr = (graph?.nodes || []).map((n) => Number(n.risk ?? 0)).filter((x) => Number.isFinite(x)).sort((a,b)=>a-b)
    const q = (p: number) => {
      if (!arr.length) return 0
      const idx = Math.min(arr.length - 1, Math.max(0, Math.floor(p * (arr.length - 1))))
      return arr[idx]
    }
    return { p50: q(0.5), p90: q(0.9) }
  }, [graph?.nodes])

  const ctxNode = useMemo(() => {
    if (!ctxMenu?.path || !graph?.nodes?.length) return null
    const p = ctxMenu.path
    return graph.nodes.find((n) => n.path === p || n.id === p) ?? null
  }, [ctxMenu?.path, graph?.nodes])

  const ctxPinned = Boolean(ctxMenu?.path && pinnedPaths.includes(ctxMenu.path))

  const truncated = Boolean(meta?.truncated)
  const showLimitBanner = Boolean(graph && (truncated || limitedMode))

  const selectedInGraph = useMemo(() => {
    if (!graph || !selectedPath) return false
    return graph.nodes.some((n) => n.path === selectedPath || n.id === selectedPath)
  }, [graph, selectedPath])

  useEffect(() => {
    let raf = 0
    let alive = true

    const tick = () => {
      if (!alive) return
      const path = selectedPath
      if (!path || !selectedInGraph) {
        setFileButtonPos(null)
        return
      }
      const next = actionsRef.current?.getRenderedPosition?.(path)
      const root = rootRef.current
      const container = containerRef.current
      if (!root || !container) {
        setFileButtonPos(null)
        return
      }
      const rootRect = root.getBoundingClientRect()
      const containerRect = container.getBoundingClientRect()
      const buttonsRect = fileButtonsRef.current?.getBoundingClientRect()
      if (buttonsRect && Number.isFinite(buttonsRect.width) && Number.isFinite(buttonsRect.height)) {
        fileButtonsSizeRef.current = { width: buttonsRect.width, height: buttonsRect.height }
      }
      if (next && Number.isFinite(next.x) && Number.isFinite(next.y)) {
        const baseX = next.x + (containerRect.left - rootRect.left)
        const baseY = next.y + (containerRect.top - rootRect.top)
        const x = baseX + 14
        const y = baseY - 14
        const { width: buttonWidth, height: buttonHeight } = fileButtonsSizeRef.current
        const pad = 8
        const minX = pad + buttonWidth / 2
        const minY = pad + buttonHeight / 2
        const maxX = Math.max(minX, rootRect.width - buttonWidth / 2 - pad)
        const maxY = Math.max(minY, rootRect.height - buttonHeight / 2 - pad)
        const nextX = clamp(x, minX, maxX)
        const nextY = clamp(y, minY, maxY)
        setFileButtonPos((prev) => {
          if (!prev) return { x: nextX, y: nextY }
          if (Math.abs(prev.x - nextX) > 0.5 || Math.abs(prev.y - nextY) > 0.5) {
            return { x: nextX, y: nextY }
          }
          return prev
        })
      } else {
        setFileButtonPos(null)
      }
      raf = window.requestAnimationFrame(tick)
    }

    if (selectedPath && selectedInGraph) {
      raf = window.requestAnimationFrame(tick)
    } else {
      setFileButtonPos(null)
    }

    return () => {
      alive = false
      if (raf) window.cancelAnimationFrame(raf)
    }
  }, [selectedPath, selectedInGraph, instanceId, leftPanelOpen, rightPanelOpen, focusGraph])

  useEffect(() => {
    if (selectedPath) return
    setFilters((prev) => ({ ...prev, onlySelectionNeighborhood: false }))
  }, [selectedPath])

  useEffect(() => {
    setFilters((prev) => {
      if (!Number.isFinite(maxRisk) || prev.minRisk <= maxRisk) return prev
      return { ...prev, minRisk: maxRisk }
    })
  }, [maxRisk])

  useEffect(() => {
    if (!filters.onlySelectionNeighborhood || !selectedPath) return
    if (selectedInGraph) return
    setFilters((prev) => ({ ...prev, onlySelectionNeighborhood: false }))
  }, [filters.onlySelectionNeighborhood, selectedInGraph, selectedPath])

  const formatRiskValue = (value: number) => (riskSliderMax > 50 ? value.toFixed(0) : value.toFixed(2))

  const graphInfo = useMemo(() => {
    if (!activeProject) return 'Pick a project'
    if (!graph) return busy ? 'loading…' : '—'

    const shown = `${returnedNodes} Nodes · ${returnedEdges} Edges`
    const totalsDiffer =
      totalNodes != null &&
      totalEdges != null &&
      (totalNodes !== returnedNodes || totalEdges !== returnedEdges || truncated || limitNodes != null)

    const totalPart = totalsDiffer
      ? ` (of ${totalNodes ?? '—'}/${totalEdges ?? '—'}${truncated ? ', truncated' : ''}${
          limitNodes ? `, limit ${limitNodes}` : ''
        })`
      : ''

    const statusSuffix = busy || stats.hydrating ? ' · loading…' : ''
    return `${shown}${totalPart}${statusSuffix}`
  }, [activeProject, graph, busy, returnedNodes, returnedEdges, totalNodes, totalEdges, truncated, limitNodes, stats.hydrating])

  const resetFilters = () => {
    setFilters(DEFAULT_FILTERS)
    setSpotlight(true)
    setLabelMode('auto')
    setEdgeDirColors(true)
  }

  const editStats = useMemo(() => actions.getEditStats(), [actions, stats.visibleNodes, selectedPath, focusGraph])
  const filtersActiveCount = useMemo(() => {
    let c = 0
    if (filters.text.trim()) c += 1
    if (filters.minRisk > 0) c += 1
    if (filters.onlySelectionNeighborhood) c += 1
    if (!spotlight) c += 1
    if (labelMode !== 'auto') c += 1
    return c
  }, [filters.minRisk, filters.onlySelectionNeighborhood, filters.text, labelMode, spotlight])

  useEffect(() => {
    if (!focusGraph) return
    const onKey = (e: KeyboardEvent) => {
      const modalCount = (() => {
        try {
          const raw = String(document.body?.dataset?.csModalOpenCount ?? '').trim()
          const n = Number(raw)
          return Number.isFinite(n) ? n : 0
        } catch {
          return 0
        }
      })()
      if (modalCount > 0) return

      const el = e.target as HTMLElement | null
      const tag = (el?.tagName || '').toLowerCase()
      const typing =
        tag === 'input' ||
        tag === 'textarea' ||
        tag === 'select' ||
        Boolean((el as any)?.isContentEditable) ||
        Boolean(el?.closest?.('input, textarea, select, [contenteditable="true"]'))
      if (typing) return

      const isMac = String((navigator as any)?.platform ?? '').toLowerCase().includes('mac')
      const mod = isMac ? e.metaKey : e.ctrlKey
      if (mod && e.key.toLowerCase() === 'z' && !e.shiftKey) {
        e.preventDefault()
        doUndo()
      }
      if (mod && (e.key.toLowerCase() === 'z') && e.shiftKey) {
        e.preventDefault()
        doRedo()
      }
      if (mod && e.key.toLowerCase() === 'y') {
        e.preventDefault()
        doRedo()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [focusGraph, doUndo, doRedo])

  useEffect(() => {
    if (workspaceView !== 'graph') return
    const onKey = (e: KeyboardEvent) => {
      const modalCount = (() => {
        try {
          const raw = String(document.body?.dataset?.csModalOpenCount ?? '').trim()
          const n = Number(raw)
          return Number.isFinite(n) ? n : 0
        } catch {
          return 0
        }
      })()
      if (modalCount > 0) return

      const el = e.target as HTMLElement | null
      const tag = (el?.tagName || '').toLowerCase()
      const typing =
        tag === 'input' ||
        tag === 'textarea' ||
        tag === 'select' ||
        Boolean((el as any)?.isContentEditable) ||
        Boolean(el?.closest?.('input, textarea, select, [contenteditable="true"]'))
      if (typing) return

      if (e.metaKey || e.ctrlKey || e.altKey) return

      const key = e.key
      if (key === 'ArrowUp' || key === 'ArrowDown') {
        if (!selectedPath) return
        const actions = actionsRef.current
        const neighbors = actions?.getNeighbors?.(selectedPath)
        const candidates = key === 'ArrowUp' ? neighbors?.inbound : neighbors?.outbound
        const nextPath =
          (candidates && candidates[0]) ||
          actions?.getNextNode?.(selectedPath, { loop: true }) ||
          null
        if (!nextPath || nextPath === selectedPath) return
        e.preventDefault()
        Promise.resolve(onNodeTap(nextPath)).then(() => actionsRef.current?.centerPath(nextPath))
        return
      }

      if (key === 'Enter') {
        if (!selectedPath) return
        e.preventDefault()
        void Promise.resolve(onOpenFileEditor(selectedPath))
        return
      }

      const keyLower = key.toLowerCase()
      if (keyLower === 'p') {
        if (!selectedPath) return
        e.preventDefault()
        void Promise.resolve(onTogglePinSelected())
        return
      }
      if (keyLower === 'h') {
        if (!selectedPath) return
        e.preventDefault()
        actionsRef.current?.hidePath(selectedPath)
        onClearSelection()
      }
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [
    onClearSelection,
    onNodeTap,
    onOpenFileEditor,
    onTogglePinSelected,
    selectedPath,
    workspaceView,
  ])

  const undoRedoControls = (
    <>
      <button
        type="button"
        className={btnClass}
        onClick={doUndo}
        disabled={!activeProject || undoStackRef.current.length === 0}
        title="Undo (Ctrl/⌘+Z)"
        aria-label="Undo (Ctrl/⌘+Z)"
      >
        {label(<UndoIcon />, 'Z')}
      </button>
      <button
        type="button"
        className={btnClass}
        onClick={doRedo}
        disabled={!activeProject || redoStackRef.current.length === 0}
        title="Redo (Ctrl/⌘+Shift+Z)"
        aria-label="Redo (Ctrl/⌘+Shift+Z)"
      >
        {label(<RedoIcon />, 'Y')}
      </button>
    </>
  )

  return (
    <div ref={rootRef} className="relative w-full h-full">
      <div ref={panelRef} className="relative absolute top-3 left-3 z-10">
        {!panelOpen ? (
          <div className="inline-flex flex-col items-start gap-1 bg-neutral-950/80 border border-neutral-800 rounded-md px-3 py-2 shadow-lg">
            <div className="w-max max-w-full shrink-0 relative left-0">
              <div className="flex items-center gap-2 flex-wrap">
                <button
                  type="button"
                  className="text-left min-w-0 flex-1"
                  onClick={() => setPanelOpen(true)}
                  disabled={!activeProject}
                  title="Open filters panel"
                >
                  <div className="text-xs text-neutral-300 truncate">
                    {activeProject ? (
                      <>
                        <span className="font-semibold">{activeProject.name}</span>
                        <span className="ml-2 text-neutral-400">{graphInfo}</span>
                      </>
                    ) : (
                      'Pick a project'
                    )}
                  </div>
                </button>
                <button
                  type="button"
                  className={toggleBtnClass}
                  onClick={onToggleWorkspaceView}
                  disabled={!activeProject}
                  title={workspaceView === 'graph' ? 'Switch to editor (Ctrl/⌘+Shift+G)' : 'Switch to graph (Ctrl/⌘+Shift+G)'}
                  aria-label={workspaceView === 'graph' ? 'Switch to editor (Ctrl/⌘+Shift+G)' : 'Switch to graph (Ctrl/⌘+Shift+G)'}
                >
                  {workspaceView === 'graph' ? <PencilIcon /> : <GraphIcon />}
                </button>
                <button
                  type="button"
                  className={btnClass}
                  onClick={() => setFocusGraph(!focusGraph)}
                  disabled={!activeProject}
                  title="F — Focus/Panels"
                  aria-label="F — Focus/Panels"
                >
                  {label(<FocusIcon />, 'F')}
                </button>
                {undoRedoControls}
                <button
                  type="button"
                  className={btnClass}
                  onClick={() => actions.fit()}
                  disabled={!activeProject || !graph}
                  title="Fit"
                  aria-label="Fit"
                >
                  {label(<FitIcon />)}
                </button>
                <button
                  type="button"
                  className={btnClass}
                  onClick={() => { if (selectedPath) actions.centerPath(selectedPath) }}
                  disabled={!activeProject || !graph || !selectedPath}
                  title="Center selected"
                  aria-label="Center selected"
                >
                  {label(<CenterIcon />)}
                </button>
                <button
                  type="button"
                  className={btnClass}
                  onClick={() => actions.relayout()}
                  disabled={!activeProject || !graph}
                  title="Relayout"
                  aria-label="Relayout"
                >
                  {label(<RelayoutIcon />)}
                </button>
                <button
                  type="button"
                  className={btnClass}
                  onClick={() => onBack?.()}
                  disabled={!activeProject || !canGoBack}
                  title="Back (Alt+← / ⌘[)"
                  aria-label="Back (Alt+← / ⌘[)"
                >
                  {label(<BackIcon />)}
                </button>
                <button
                  type="button"
                  className={btnClass}
                  onClick={() => onForward?.()}
                  disabled={!activeProject || !canGoForward}
                  title="Forward (Alt+→ / ⌘])"
                  aria-label="Forward (Alt+→ / ⌘])"
                >
                  {label(<ForwardIcon />)}
                </button>
                <button
                  type="button"
                  className={btnClass}
                  onClick={onEscAction}
                  disabled={!activeProject || (!selectedPath && !focusGraph)}
                  title="Esc — back/clear"
                  aria-label="Esc — back/clear"
                >
                  {label(<ClearIcon />, 'Esc')}
                </button>
                <button
                  type="button"
                  className={btnClass}
                  onClick={() => onTogglePinSelected()}
                  disabled={!activeProject || !selectedPath}
                  title="Pin/Unpin selected (max 3)"
                  aria-label="Pin/Unpin selected (max 3)"
                >
                  {label(isSelectedPinned ? <UnpinIcon /> : <PinIcon />)}
                </button>
                <button
                  type="button"
                  className={btnClass}
                  onClick={() => setNeighborsOpen((v) => !v)}
                  disabled={!activeProject || !selectedPath}
                  title="Show incoming/outgoing edges"
                  aria-label="Show incoming/outgoing edges"
                >
                  {label(<NeighborsIcon />)}
                </button>
                <button
                  type="button"
                  className="shrink-0 rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
                  onClick={() => setHelpOpen(true)}
                  title="What this is and how to use it"
                >
                  ?
                </button>
              </div>
            </div>
            {selectionTrail?.length > 0 && (
              <div className="w-full max-w-[520px] min-w-0 overflow-x-auto">
                <div className="flex flex-wrap items-center gap-1">
                  <span className="text-[10px] text-neutral-500">Trail:</span>
                  {selectionTrail.map((p) => {
                    const active = selectedPath === p
                    return (
                      <button
                        key={p}
                        type="button"
                        className={[
                          'px-2 py-0.5 rounded-full border text-[11px] max-w-[220px] truncate',
                          active ? 'bg-neutral-800 border-neutral-700 text-neutral-100' : 'bg-neutral-950 border-neutral-800 text-neutral-200 hover:border-neutral-700',
                        ].join(' ')}
                        onClick={() => void goTo(p)}
                        title={p}
                        disabled={!activeProject}
                      >
                        {baseName(p)}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}
            {neighborsOpen && selectedPath && (
              <div className="mt-2 grid grid-cols-2 gap-2">
                <div className="rounded-md border border-neutral-800 bg-neutral-950 p-2">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: EDGE_IN_COLOR }} />
                    <div className="text-[10px] uppercase tracking-wide text-neutral-400">Inbound</div>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {(neighbors.inbound || []).slice(0, 18).map((p) => (
                      <button
                        key={p}
                        type="button"
                        className="px-2 py-0.5 rounded-full border border-neutral-800 bg-neutral-950 text-[11px] text-neutral-200 hover:border-neutral-700 max-w-[220px] truncate"
                        onClick={() => void goTo(p)}
                        title={p}
                      >
                        {baseName(p)}
                      </button>
                    ))}
                    {!neighbors.inbound.length && <div className="text-[11px] text-neutral-500">—</div>}
                  </div>
                </div>

                <div className="rounded-md border border-neutral-800 bg-neutral-950 p-2">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: EDGE_OUT_COLOR }} />
                    <div className="text-[10px] uppercase tracking-wide text-neutral-400">Outbound</div>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {(neighbors.outbound || []).slice(0, 18).map((p) => (
                      <button
                        key={p}
                        type="button"
                        className="px-2 py-0.5 rounded-full border border-neutral-800 bg-neutral-950 text-[11px] text-neutral-200 hover:border-neutral-700 max-w-[220px] truncate"
                        onClick={() => void goTo(p)}
                        title={p}
                      >
                        {baseName(p)}
                      </button>
                    ))}
                    {!neighbors.outbound.length && <div className="text-[11px] text-neutral-500">—</div>}
                  </div>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-2 bg-neutral-950/80 border border-neutral-800 rounded-md px-3 py-2 shadow-lg">
            <div className="flex items-center gap-3">
              <div className="text-xs text-neutral-300">
                {activeProject ? (
                  <>
                    <span className="font-semibold">{activeProject.name}</span>
                    <span className="ml-2 text-neutral-400">{graphInfo}</span>
                  </>
                ) : (
                  'Pick a project'
                )}
              </div>
              <div className="ml-auto flex items-center gap-2">
                {undoRedoControls}
                <button
                  type="button"
                  className={toggleBtnClass}
                  onClick={onToggleWorkspaceView}
                  disabled={!activeProject}
                  title={workspaceView === 'graph' ? 'Switch to editor (Ctrl/⌘+Shift+G)' : 'Switch to graph (Ctrl/⌘+Shift+G)'}
                  aria-label={workspaceView === 'graph' ? 'Switch to editor (Ctrl/⌘+Shift+G)' : 'Switch to graph (Ctrl/⌘+Shift+G)'}
                >
                  {workspaceView === 'graph' ? <PencilIcon /> : <GraphIcon />}
                </button>
                <button
                  type="button"
                  className="text-xs text-neutral-300 hover:text-white"
                  onClick={() => setPanelOpen(false)}
                  aria-label="Collapse panel"
                  title="Collapse"
                >
                  <ClearIcon />
                </button>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs text-neutral-200">
              <label className="flex items-center gap-2 col-span-2">
                <input
                  type="checkbox"
                  checked={spotlight}
                  onChange={(e) => setSpotlight(e.target.checked)}
                  disabled={!activeProject}
                />
                <span className="text-[11px] text-neutral-300">
                  Spotlight: highlight selected node edges and dim the rest (no hiding)
                </span>
              </label>

              <label className="flex items-center gap-2 col-span-2">
                <input
                  type="checkbox"
                  checked={edgeDirColors}
                  onChange={(e) => setEdgeDirColors(e.target.checked)}
                  disabled={!activeProject}
                />
                <span className="text-[11px] text-neutral-300">
                  Direction Colors: <span className="font-mono" style={{ color: EDGE_IN_COLOR }}>IN</span> /
                  <span className="font-mono ml-1" style={{ color: EDGE_OUT_COLOR }}>OUT</span> for edges of the selected node
                </span>
              </label>

              <label className="flex flex-col gap-1">
                <span className="text-[11px] text-neutral-400">Labels</span>
                <select
                  className="rounded-md bg-neutral-900 border border-neutral-800 px-2 py-1"
                  value={labelMode}
                  onChange={(e) => setLabelMode(e.target.value as LabelMode)}
                  disabled={!activeProject}
                >
                  <option value="auto">AUTO</option>
                  <option value="on">ON</option>
                  <option value="off">OFF</option>
                </select>
              </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] text-neutral-400">Filter</span>
            <input
              className="rounded-md bg-neutral-900 border border-neutral-800 px-2 py-1"
              value={filters.text}
              onChange={(e) => setFilters((prev) => ({ ...prev, text: e.target.value }))}
              placeholder="e.g., service/"
              disabled={!activeProject}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] text-neutral-400">Risk</span>
            <div className="flex items-center gap-2">
              <input
                type="range"
                min={0}
                max={riskSliderMax}
                step={riskStep}
                value={Math.min(filters.minRisk, riskSliderMax)}
                onChange={(e) => setFilters((prev) => ({ ...prev, minRisk: Number(e.target.value) }))}
                disabled={!activeProject}
                className="flex-1"
              />
              <span className="w-14 text-right text-[11px] text-neutral-400">{formatRiskValue(filters.minRisk)}</span>
            </div>
            <div className="mt-1">
              <div className="h-2 rounded bg-gradient-to-r from-green-500 via-yellow-500 to-red-500 opacity-80" />
              <div className="mt-1 text-[10px] text-neutral-500">
                Low → High (Backend Score) · p50 {riskQuantiles.p50.toFixed(2)} · p90 {riskQuantiles.p90.toFixed(2)}
              </div>
            </div>
          </label>
          <label className="flex items-center gap-2 col-span-2">
            <input
              type="checkbox"
              checked={filters.onlySelectionNeighborhood && !!selectedPath && selectedInGraph}
              onChange={(e) =>
                setFilters((prev) => ({ ...prev, onlySelectionNeighborhood: e.target.checked && !!selectedPath }))
              }
              disabled={!activeProject || !selectedPath || !selectedInGraph}
            />
            <span className="text-[11px] text-neutral-300">
              Nodes around the selected file
              {!selectedPath && ' (select a node)'}
              {selectedPath && !selectedInGraph && ' (not in graph)'}
            </span>
          </label>
            <div className="flex items-center gap-2 col-span-2">
              <button
                className={btnClass}
                onClick={resetFilters}
                disabled={!activeProject}
                title="Reset filters"
                aria-label="Reset filters"
              >
                {label(<ResetFiltersIcon />)}
              </button>
              <button
                type="button"
                className={btnClass}
                onClick={() => actions.relayout()}
                disabled={!activeProject || !graph}
                title="Relayout"
                aria-label="Relayout"
              >
                {label(<RelayoutIcon />)}
              </button>
              <button
                type="button"
                className={btnClass}
                onClick={() => setFocusGraph(!focusGraph)}
                disabled={!activeProject}
                title="Focus/Panels"
                aria-label="Focus/Panels"
              >
                {label(<FocusIcon />, 'F')}
              </button>
              <button
                type="button"
                className={btnClass}
                onClick={onEscAction}
                disabled={!activeProject || (!selectedPath && !focusGraph)}
                title="Esc — back/clear"
                aria-label="Esc — back/clear"
              >
                {label(<ClearIcon />, 'Esc')}
              </button>
              <div className="text-[11px] text-neutral-400">
                Showing {stats.visibleNodes} / {stats.totalNodes || returnedNodes} nodes
              </div>
            </div>
            </div>
          </div>
        )}
      </div>
      {stats.hydrating && (
        <div
          className="absolute left-3 z-10 rounded-md bg-neutral-950/80 border border-neutral-800 px-3 py-2 text-[11px] text-neutral-300 shadow-lg"
          style={{ bottom: pinnedPaths.length ? 220 : 12 }}
        >
          {compactMode ? 'Loading…' : 'Loading a large graph in batches to avoid freezing the browser…'}
        </div>
      )}
      {showLimitBanner && (
        <div
          className={[
            'group absolute right-3 z-10 rounded-md bg-amber-950/70 border border-amber-800 px-3 py-2 text-[11px] text-amber-200 shadow-lg',
            activeProject ? 'bottom-20' : 'bottom-3',
          ].join(' ')}
          title="Graph limit: hover shows details"
        >
          <div className="font-semibold">
            {truncated ? 'Truncated' : 'Limited'}
            {limitNodes ? ` · top-N=${limitNodes}` : ''}
            {' · '}
            Nodes {returnedNodes}{totalNodes != null ? `/${totalNodes}` : ''}
          </div>
          <div className={compactMode ? hoverRevealBlock : ''}>
            {truncated ? (
              <>Graph is truncated on the backend. Increase the limit/mode or refine filters.</>
            ) : (
              <>Top-N mode. Increase N or switch graph mode (full/local) to see more.</>
            )}
          </div>
        </div>
      )}
      {activeProject && !graph && !busy && (
        <div className="absolute inset-0 z-[5] flex items-center justify-center">
          <div className="max-w-[520px] rounded-md bg-neutral-950/80 border border-neutral-800 p-4 shadow-lg">
            <div className="text-sm font-semibold text-neutral-100">Graph is not displayed yet</div>
            <div className="mt-2 text-xs text-neutral-300 space-y-2">
              {graphMode === 'local' && !selectedPath && (
                <div>Mode <span className="font-mono">Local</span>: select a file first.</div>
              )}
              <div className="flex flex-wrap gap-2 pt-1">
                {graphMode === 'local' && !selectedPath && (
                  <button
                    className="rounded-md bg-indigo-600 hover:bg-indigo-500 px-3 py-2 text-xs font-semibold"
                    type="button"
                    onClick={onOpenPalette}
                  >
                    Pick File (Ctrl/⌘+K)
                  </button>
                )}
                <button
                  className="rounded-md bg-neutral-800 hover:bg-neutral-700 px-3 py-2 text-xs font-semibold disabled:opacity-50"
                  type="button"
                  onClick={() => void onScan()}
                  disabled={!activeProject}
                >
                  Scan
                </button>
                <button
                  className="rounded-md bg-neutral-900 hover:bg-neutral-800 px-3 py-2 text-xs font-semibold disabled:opacity-50"
                  type="button"
                  onClick={() => void onRefresh()}
                  disabled={!activeProject}
                >
                  Refresh
                </button>
              </div>
              <div className="text-[11px] text-neutral-500">
                Tip: for a first pass, <span className="font-mono">top-N</span> or <span className="font-mono">full</span> is easier.
              </div>
            </div>
          </div>
        </div>
      )}
      {pinnedPaths.length > 0 && (
        <div className="group absolute bottom-3 left-3 z-10 w-[360px] max-w-[calc(100vw-24px)] rounded-md bg-neutral-950/80 border border-neutral-800 px-3 py-2 shadow-lg">
          <div className="flex items-center justify-between gap-2">
            <div className="text-xs font-semibold text-neutral-200">
              Pinned ({pinnedPaths.length}/3)
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
                onClick={() => onClearPins()}
                title="Clear all pins"
                aria-label="Clear all pins"
              >
                {label(<ClearIcon />)}
              </button>
            </div>
          </div>
          <div className="mt-2 flex flex-col gap-2">
            {pinnedPaths.map((p) => {
              const n = graph?.nodes?.find((x) => x.path === p || x.id === p)
              const active = selectedPath === p
              const risk = n ? Number(n.risk ?? 0) : null
              const loc = n ? Number(n.loc ?? 0) : null
              const fi = n ? Number(n.fan_in ?? 0) : null
              const fo = n ? Number(n.fan_out ?? 0) : null
              return (
                <div
                  key={p}
                  className={[
                    'rounded-md border px-2 py-2',
                    active ? 'bg-neutral-900 border-neutral-700' : 'bg-neutral-950 border-neutral-900',
                  ].join(' ')}
                  title={p}
                >
                  <div className="flex items-start justify-between gap-2">
                    <button
                      type="button"
                      className="min-w-0 flex-1 text-left"
                      onClick={() => void goTo(p)}
                      title="Go to node"
                    >
                      <div className="text-xs font-semibold text-neutral-100 truncate">
                        {baseName(p)}
                        {compactMode && (
                          <span className="ml-2 text-[11px] text-neutral-400">
                            R:{risk != null ? risk.toFixed(2) : '—'}
                          </span>
                        )}
                      </div>
                      {!compactMode && <div className="text-[11px] text-neutral-500 truncate">{p}</div>}
                    </button>
                    <button
                      type="button"
                      className="shrink-0 text-neutral-400 hover:text-neutral-100"
                      onClick={() => onUnpin(p)}
                      aria-label="Unpin"
                      title="Unpin"
                    >
                      ×
                    </button>
                  </div>
                  {!compactMode && (
                    <div className="mt-1 text-[11px] text-neutral-300">
                      Risk: <span className="text-neutral-100">{risk != null ? risk.toFixed(2) : '—'}</span>
                      {' · '}
                      LOC: <span className="text-neutral-100">{loc != null ? String(loc) : '—'}</span>
                      {' · '}
                      In: <span className="text-neutral-100">{fi != null ? String(fi) : '—'}</span>
                      {' · '}
                      Out: <span className="text-neutral-100">{fo != null ? String(fo) : '—'}</span>
                      {!n && <span className="text-neutral-500"> · not in current graph</span>}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
          {pinnedPaths.length >= 2 && (
            <div className={['mt-3 border-t border-neutral-800 pt-2', hoverRevealBlock].join(' ')}>
              <div className="text-[11px] text-neutral-400 font-semibold">Compare (Δ vs first pinned)</div>
              {(() => {
                const basePath = pinnedPaths[0]
                const base = graph?.nodes?.find((x) => x.path === basePath || x.id === basePath)
                const br = base ? Number(base.risk ?? 0) : null
                const bl = base ? Number(base.loc ?? 0) : null
                const bi = base ? Number(base.fan_in ?? 0) : null
                const bo = base ? Number(base.fan_out ?? 0) : null
                return (
                  <div className="mt-1 space-y-1">
                    {pinnedPaths.slice(1).map((pp) => {
                      const n = graph?.nodes?.find((x) => x.path === pp || x.id === pp)
                      const r = n ? Number(n.risk ?? 0) : null
                      const l = n ? Number(n.loc ?? 0) : null
                      const fi = n ? Number(n.fan_in ?? 0) : null
                      const fo = n ? Number(n.fan_out ?? 0) : null
                      const d = (a: number | null, b: number | null) => (a != null && b != null ? (a - b) : null)
                      return (
                        <div key={pp} className="text-[11px] text-neutral-300">
                          <span className="text-neutral-100">{baseName(pp)}</span>
                          {' · '}
                          ΔRisk: <span className="text-neutral-100">{d(r, br)?.toFixed?.(2) ?? '—'}</span>
                          {' · '}
                          ΔLOC: <span className="text-neutral-100">{d(l, bl) != null ? String(d(l, bl)) : '—'}</span>
                          {' · '}
                          ΔIn/Out: <span className="text-neutral-100">{d(fi, bi) != null && d(fo, bo) != null ? `${d(fi, bi)}/${d(fo, bo)}` : '—'}</span>
                        </div>
                      )
                    })}
                  </div>
                )
              })()}
            </div>
          )}
        </div>
      )}
      <GraphHelpModal open={helpOpen} onClose={() => setHelpOpen(false)} />
      {fileButtonPos && selectedPath && activeProject && selectedInGraph && (
        <div
          ref={fileButtonsRef}
          className="absolute z-20 flex items-center gap-1"
          style={{ left: fileButtonPos.x, top: fileButtonPos.y, transform: 'translate(-50%, -50%)' }}
        >
          <button
            type="button"
            className="flex h-6 w-6 items-center justify-center rounded-full border border-neutral-700 bg-neutral-950/90 text-neutral-200 shadow hover:border-neutral-500 hover:bg-neutral-900"
            title="View/edit file"
            aria-label="View/edit file"
            onMouseDown={(e) => e.stopPropagation()}
            onClick={() => void onOpenFileEditor(selectedPath)}
          >
            <EyeIcon />
          </button>
          <button
            type="button"
            className="flex h-6 w-6 items-center justify-center rounded-full border border-neutral-700 bg-neutral-950/90 text-neutral-200 shadow hover:border-neutral-500 hover:bg-neutral-900 disabled:opacity-50"
            title={quickSummaryTitleFor(selectedPath)}
            aria-label="Quick summary"
            onMouseDown={(e) => e.stopPropagation()}
            onClick={() => void Promise.resolve(onQuickSummary(selectedPath))}
            disabled={isQuickSummaryDisabledFor(selectedPath)}
          >
            <SummaryIcon />
          </button>
        </div>
      )}
      {ctxMenu && (
        <div
          ref={ctxMenuRef}
          className="absolute z-[60] w-[280px] rounded-md border border-neutral-800 bg-neutral-950/95 shadow-xl p-2"
          style={{ left: ctxMenu.x, top: ctxMenu.y }}
        >
          <div className="px-2 py-1">
            <div className="text-xs font-semibold text-neutral-100 truncate">{baseName(ctxMenu.path)}</div>
            <div className="text-[11px] text-neutral-500 truncate">{ctxMenu.path}</div>
            <div className="mt-1 text-[11px] text-neutral-300">
              Risk: <span className="text-neutral-100">{ctxNode ? Number(ctxNode.risk ?? 0).toFixed(2) : '—'}</span>
              {' · '}
              LOC: <span className="text-neutral-100">{ctxNode ? String(ctxNode.loc ?? '—') : '—'}</span>
              {' · '}
              In/Out:{' '}
              <span className="text-neutral-100">
                {ctxNode ? `${ctxNode.fan_in ?? 0}/${ctxNode.fan_out ?? 0}` : '—'}
              </span>
            </div>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-2 px-1">
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
              onClick={() => { actions.centerPath(ctxMenu.path); setCtxMenu(null) }}
            >
              Center
            </button>
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
              onClick={async () => { await Promise.resolve(onTogglePinPath(ctxMenu.path)); setCtxMenu(null) }}
            >
              {ctxPinned ? 'Unpin' : 'Pin'}
            </button>
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
              onClick={() => { void Promise.resolve(onOpenFileEditor(ctxMenu.path)); setCtxMenu(null) }}
            >
              Open in editor
            </button>
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold disabled:opacity-50"
              onClick={() => { void Promise.resolve(onQuickSummary(ctxMenu.path)); setCtxMenu(null) }}
              title={quickSummaryTitleFor(ctxMenu.path)}
              disabled={isQuickSummaryDisabledFor(ctxMenu.path)}
            >
              Quick summary
            </button>
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
              onClick={() => { pushUndo(actions.exportSnapshot()); actions.toggleLockPath(ctxMenu.path); setCtxMenu(null); notifyInfo('Lock toggled') }}
              title="Lock/unlock node position (freeze)"
            >
              Lock/Unlock
            </button>
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
              onClick={() => { pushUndo(actions.exportSnapshot()); actions.unlockAll(); setCtxMenu(null); notifyInfo('Unlocked all') }}
              title="Unlock all nodes"
            >
              Unlock All
            </button>
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
              onClick={() => {
                pushUndo(actions.exportSnapshot())
                if (selectedPath === ctxMenu.path) onClearSelection()
                actions.hidePath(ctxMenu.path)
                setCtxMenu(null)
                notifyInfo('Node hidden')
              }}
              title="Hide node"
            >
              Hide node
            </button>
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
              onClick={() => { pushUndo(actions.exportSnapshot()); actions.hideOthers(ctxMenu.path); setCtxMenu(null); notifyInfo('Others hidden') }}
              title="Keep only node neighborhood"
            >
              Hide Others
            </button>

            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
              onClick={() => { pushUndo(actions.exportSnapshot()); actions.showAll(); setCtxMenu(null); notifyInfo('Show all') }}
              title="Show all hidden nodes"
            >
              Show All
            </button>
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
              onClick={() => { pushUndo(actions.exportSnapshot()); actions.relayoutVisible(); setCtxMenu(null); notifyInfo('Relayout visible') }}
              title="Relayout only visible nodes"
            >
              Relayout visible
            </button>

            <button
              type="button"
              className="rounded-md bg-neutral-800 hover:bg-neutral-700 px-2 py-1 text-[11px] font-semibold"
              onClick={() => { saveLayout(); setCtxMenu(null) }}
              title="Save layout"
            >
              Save layout
            </button>
            <button
              type="button"
              className="rounded-md bg-neutral-800 hover:bg-neutral-700 px-2 py-1 text-[11px] font-semibold"
              onClick={() => { resetLayout(); setCtxMenu(null) }}
              title="Reset layout"
            >
              Reset layout
            </button>
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
              onClick={async () => {
                try { await navigator.clipboard.writeText(ctxMenu.path) } catch {}
                notifyInfo('Path copied')
                setCtxMenu(null)
              }}
            >
              Copy Path
            </button>
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
              onClick={() => { setNeighborsOpen(true); setCtxMenu(null) }}
              disabled={!ctxMenu.path}
            >
              Neighbors
            </button>
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
              onClick={() => { actions.fit(); setCtxMenu(null) }}
            >
              Fit
            </button>
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
              onClick={() => { actions.relayout(); setCtxMenu(null) }}
            >
              Relayout
            </button>
          </div>
        </div>
      )}
      {/* Status bar */}
      {activeProject && (
        <div className="absolute bottom-3 right-3 z-10 flex max-w-[calc(100%-24px)] flex-wrap items-end gap-2">
          <div className="group max-w-[calc(100%-24px)] rounded-md bg-neutral-950/80 border border-neutral-800 px-3 py-2 shadow-lg text-[11px] text-neutral-300 break-words">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-neutral-400">Mode:</span> <span className="text-neutral-100 font-semibold">{graphMode}</span>
              <span className="text-neutral-500">·</span>
              <span>Nodes: <span className="text-neutral-100">{stats.visibleNodes}</span>/{returnedNodes}</span>
              <span className="text-neutral-500">·</span>
              <span>Edges: <span className="text-neutral-100">{returnedEdges}</span></span>
              {selectedPath && (
                <>
                  <span className="text-neutral-500">·</span>
                  <span className="truncate max-w-[260px]">Sel: <span className="text-neutral-100">{baseName(selectedPath)}</span></span>
                </>
              )}
            </div>
            <div className={['mt-2 flex flex-wrap items-center gap-2 border-t border-neutral-800/70 pt-2', hoverRevealFlex].join(' ')}>
              <div className="flex items-center gap-2 rounded-md border border-neutral-800 bg-neutral-900/60 px-2 py-1 text-[10px] text-neutral-300">
                <span className="flex items-center gap-1">
                  <EyeIcon />
                  <span className="text-neutral-100">{editStats.hidden}</span>
                </span>
                <span className="text-neutral-500">·</span>
                <span className="flex items-center gap-1">
                  <LockIcon />
                  <span className="text-neutral-100">{editStats.locked}</span>
                </span>
              </div>
              <span className="h-4 w-px bg-neutral-800/80" aria-hidden="true" />
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className={btnClass}
                  onClick={() => setPanelOpen(true)}
                  title="Open filters panel"
                  aria-label="Open filters panel"
                >
                  <span className="relative inline-flex items-center">
                    <FilterIcon />
                    {filtersActiveCount > 0 && (
                      <span className="absolute -right-2 -top-2 rounded-full bg-indigo-500 px-1 text-[8px] font-semibold text-white">
                        {filtersActiveCount}
                      </span>
                    )}
                  </span>
                </button>
                <button
                  type="button"
                  className={btnClass}
                  onClick={() => { pushUndo(actions.exportSnapshot()); actions.showAll(); notifyInfo('Show all') }}
                  disabled={editStats.hidden === 0}
                  title="Show all hidden nodes"
                  aria-label="Show all hidden nodes"
                >
                  {label(<EyeIcon />)}
                </button>
                <button
                  type="button"
                  className={btnClass}
                  onClick={saveLayout}
                  title="Save layout"
                  aria-label="Save layout"
                >
                  {label(<SaveLayoutIcon />)}
                </button>
                <button
                  type="button"
                  className={btnClass}
                  onClick={resetLayout}
                  title="Reset layout"
                  aria-label="Reset layout"
                >
                  {label(<ResetLayoutIcon />)}
                </button>
              </div>
            </div>
            {compactMode && (
              <div className="mt-1 text-[10px] text-neutral-500">
                Hover for controls
              </div>
            )}
          </div>
        </div>
      )}
      <div
        ref={containerRef}
        className="graph-canvas-bg w-full h-full"
        onContextMenu={(e) => e.preventDefault()}
        aria-label={focusGraph ? 'Graph focus active' : undefined}
      />
    </div>
  )
}
