// frontend/src/ui/components/GraphCanvas.tsx
import React, { useCallback, useEffect, useMemo, useRef } from 'react'
import type { GraphData, Project } from '@/api'
import { 
  useCytoscapeGraph, type GraphFilters,
  type LabelMode,
  type CytoscapeGraphActions,
} from './useCytoscapeGraph'
import { Modal } from '@/shared/ui/Modal'
import {
  EDGE_IN_COLOR,
  EDGE_OUT_COLOR,
  DEFAULT_FILTERS,
} from './GraphCanvas.storage'
import { useGraphFilters } from './useGraphFilters'
import { useGraphHistory } from './useGraphHistory'
import { GraphControlPanel, type GraphControlView } from './GraphControlPanel'
import { useGraphKeyboard } from './useGraphKeyboard'
import { useGraphLayout } from './useGraphLayout'
import { useGraphPanels } from './useGraphPanels'
import { useGraphContextMenu } from './useGraphContextMenu'
import { GraphLoadingBanner, GraphLimitBanner, GraphEmptyState, GraphFileButtons } from './GraphOverlays'
import { GraphHelpModal } from './GraphCanvas.HelpModal'
import { baseName, clamp } from './GraphCanvas.helpers'
import { GraphContextMenu } from './GraphContextMenu'
import { GraphStatusBar } from './GraphStatusBar'
import { GraphPinsPanel } from './GraphPinsPanel'

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

  const {
    ctxMenu, setCtxMenu, fileButtonPos, setFileButtonPos,
    ctxMenuRef, fileButtonsRef, fileButtonsSizeRef, openNodeMenu,
  } = useGraphContextMenu({ rootRef })

  const onEscAction = useCallback(() => {
    setCtxMenu(null)
    if (focusGraph) return void setFocusGraph(false)
    if (selectedPath) return void onClearSelection()
  }, [focusGraph, onClearSelection, selectedPath, setFocusGraph])

  const actionsRef = useRef<CytoscapeGraphActions | null>(null)
  const notifyRef = useRef<(msg: string) => void>(() => {})
  useEffect(() => { notifyRef.current = notifyInfo }, [notifyInfo])

  const {
    undoStackRef, redoStackRef, dragBeforeRef, pushUndo, doUndo, doRedo, clearHistory,
  } = useGraphHistory({ actionsRef, notifyRef, onRegisterUndoRedo })


  const projectId = activeProject?.id ?? null

  const {
    filters, setFilters, labelMode, setLabelMode,
    spotlight, setSpotlight, edgeDirColors, setEdgeDirColors,
  } = useGraphFilters(projectId)
  const isGraphActive = focusGraph || workspaceView === 'graph'

  const {
    panelOpen, setPanelOpen, neighborsOpen, setNeighborsOpen, helpOpen, setHelpOpen,
    panelRef, neighbors,
  } = useGraphPanels({ graph, selectedPath })

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
    clearHistory()
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

  const { saveLayout, resetLayout } = useGraphLayout({
    activeProject,
    graphMode,
    selectedPath,
    graph,
    instanceId,
    actions,
    actionsRef,
    notifyInfo,
    notifyRef,
    pushUndo,
  })

  const maxRisk = useMemo(() => {
    if (!graph?.nodes?.length) return 0
    return graph.nodes.reduce((acc, n) => Math.max(acc, Number(n.risk ?? 0)), 0)
  }, [graph])

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

  useGraphKeyboard({
    focusGraph,
    doUndo,
    doRedo,
    workspaceView,
    selectedPath,
    actionsRef,
    onNodeTap,
    onOpenFileEditor,
    onTogglePinSelected,
    onClearSelection,
  })

  const controlView: GraphControlView = {
    graph, activeProject, busy, selectedPath, selectedInGraph, workspaceView,
    focusGraph, setFocusGraph, panelOpen, setPanelOpen, neighborsOpen, setNeighborsOpen,
    setHelpOpen, panelRef, filters, setFilters, labelMode, setLabelMode,
    spotlight, setSpotlight, edgeDirColors, setEdgeDirColors, actions, stats, neighbors,
    selectionTrail, returnedNodes, returnedEdges, totalNodes, totalEdges, limitNodes, truncated,
    isSelectedPinned, onTogglePinSelected, onToggleWorkspaceView, canGoBack, canGoForward,
    onBack, onForward, goTo, onEscAction, resetFilters, doUndo, doRedo,
    undoStackRef, redoStackRef, label, btnClass, toggleBtnClass,
  }

  return (
    <div ref={rootRef} className="relative w-full h-full">
      <GraphControlPanel view={controlView} />
      <GraphLoadingBanner hydrating={stats.hydrating} pinnedCount={pinnedPaths.length} compactMode={compactMode} />
      <GraphLimitBanner
        show={showLimitBanner}
        activeProject={activeProject}
        truncated={truncated}
        limitNodes={limitNodes}
        returnedNodes={returnedNodes}
        totalNodes={totalNodes}
        compactMode={compactMode}
        hoverRevealBlock={hoverRevealBlock}
      />
      <GraphEmptyState
        activeProject={activeProject}
        graph={graph}
        busy={busy}
        graphMode={graphMode}
        selectedPath={selectedPath}
        onOpenPalette={onOpenPalette}
        onScan={onScan}
        onRefresh={onRefresh}
      />
      <GraphPinsPanel
        pinnedPaths={pinnedPaths}
        graph={graph}
        selectedPath={selectedPath}
        compactMode={compactMode}
        hoverRevealBlock={hoverRevealBlock}
        label={label}
        onGoTo={goTo}
        onUnpin={onUnpin}
        onClearPins={onClearPins}
      />
      <GraphHelpModal open={helpOpen} onClose={() => setHelpOpen(false)} />
      <GraphFileButtons
        fileButtonPos={fileButtonPos}
        selectedPath={selectedPath}
        activeProject={activeProject}
        selectedInGraph={selectedInGraph}
        fileButtonsRef={fileButtonsRef}
        onOpenFileEditor={onOpenFileEditor}
        onQuickSummary={onQuickSummary}
        quickSummaryTitleFor={quickSummaryTitleFor}
        isQuickSummaryDisabledFor={isQuickSummaryDisabledFor}
      />
      <GraphContextMenu
        ctxMenu={ctxMenu}
        menuRef={ctxMenuRef}
        ctxNode={ctxNode}
        ctxPinned={ctxPinned}
        selectedPath={selectedPath}
        actions={actions}
        onClose={() => setCtxMenu(null)}
        onOpenNeighbors={() => setNeighborsOpen(true)}
        onTogglePinPath={onTogglePinPath}
        onOpenFileEditor={onOpenFileEditor}
        onQuickSummary={onQuickSummary}
        onClearSelection={onClearSelection}
        pushUndo={pushUndo}
        saveLayout={saveLayout}
        resetLayout={resetLayout}
        notifyInfo={notifyInfo}
        quickSummaryTitleFor={quickSummaryTitleFor}
        isQuickSummaryDisabledFor={isQuickSummaryDisabledFor}
      />
      <GraphStatusBar
        activeProject={activeProject}
        graphMode={graphMode}
        visibleNodes={stats.visibleNodes}
        returnedNodes={returnedNodes}
        returnedEdges={returnedEdges}
        selectedPath={selectedPath}
        editStats={editStats}
        filtersActiveCount={filtersActiveCount}
        compactMode={compactMode}
        hoverRevealFlex={hoverRevealFlex}
        btnClass={btnClass}
        label={label}
        actions={actions}
        onOpenPanel={() => setPanelOpen(true)}
        pushUndo={pushUndo}
        notifyInfo={notifyInfo}
        saveLayout={saveLayout}
        resetLayout={resetLayout}
      />
      <div
        ref={containerRef}
        className="graph-canvas-bg w-full h-full"
        onContextMenu={(e) => e.preventDefault()}
        aria-label={focusGraph ? 'Graph focus active' : undefined}
      />
    </div>
  )
}
