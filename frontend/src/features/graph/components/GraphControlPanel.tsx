import React, { useMemo } from 'react'
import type { Dispatch, SetStateAction, MutableRefObject, ReactNode } from 'react'
import type { GraphData, Project } from '@/api'
import type { GraphFilters, LabelMode, CytoscapeGraphActions, GraphEditSnapshot } from '../hooks/useCytoscapeGraph'
import type { GraphStats } from '../lib/useCytoscapeGraph.constants'
import { EDGE_IN_COLOR, EDGE_OUT_COLOR } from '../lib/GraphCanvas.storage'
import { baseName } from '../lib/GraphCanvas.helpers'
import {
  GraphIcon, PencilIcon, UndoIcon, RedoIcon, FitIcon, CenterIcon, RelayoutIcon,
  BackIcon, ForwardIcon, ClearIcon, PinIcon, UnpinIcon, FocusIcon, ResetFiltersIcon, NeighborsIcon,
} from './GraphCanvas.icons'

export type GraphControlView = {
  graph: GraphData | null
  activeProject: Project | null
  busy: boolean
  selectedPath: string | null
  selectedInGraph: boolean
  workspaceView: 'graph' | 'editor'
  focusGraph: boolean
  setFocusGraph: (v: boolean) => void
  panelOpen: boolean
  setPanelOpen: Dispatch<SetStateAction<boolean>>
  neighborsOpen: boolean
  setNeighborsOpen: Dispatch<SetStateAction<boolean>>
  setHelpOpen: Dispatch<SetStateAction<boolean>>
  panelRef: MutableRefObject<HTMLDivElement | null>
  filters: GraphFilters
  setFilters: Dispatch<SetStateAction<GraphFilters>>
  labelMode: LabelMode
  setLabelMode: Dispatch<SetStateAction<LabelMode>>
  spotlight: boolean
  setSpotlight: Dispatch<SetStateAction<boolean>>
  edgeDirColors: boolean
  setEdgeDirColors: Dispatch<SetStateAction<boolean>>
  actions: CytoscapeGraphActions
  stats: GraphStats
  neighbors: { inbound: string[]; outbound: string[] }
  selectionTrail: string[]
  returnedNodes: number
  returnedEdges: number
  totalNodes: number | null
  totalEdges: number | null
  limitNodes: number | null
  truncated: boolean
  isSelectedPinned: boolean
  onTogglePinSelected: () => void | Promise<void>
  onToggleWorkspaceView: () => void
  canGoBack?: boolean
  canGoForward?: boolean
  onBack?: () => void
  onForward?: () => void
  goTo: (path: string) => void | Promise<void>
  onEscAction: () => void
  resetFilters: () => void
  doUndo: () => void
  doRedo: () => void
  undoStackRef: MutableRefObject<GraphEditSnapshot[]>
  redoStackRef: MutableRefObject<GraphEditSnapshot[]>
  label: (icon: ReactNode, hotkey?: string) => ReactNode
  btnClass: string
  toggleBtnClass: string
}

export function GraphControlPanel({ view }: { view: GraphControlView }) {
  const {
    graph, activeProject, busy, selectedPath, selectedInGraph, workspaceView,
    focusGraph, setFocusGraph, panelOpen, setPanelOpen, neighborsOpen, setNeighborsOpen,
    setHelpOpen, panelRef, filters, setFilters, labelMode, setLabelMode,
    spotlight, setSpotlight, edgeDirColors, setEdgeDirColors, actions, stats, neighbors,
    selectionTrail, returnedNodes, returnedEdges, totalNodes, totalEdges, limitNodes, truncated,
    isSelectedPinned, onTogglePinSelected, onToggleWorkspaceView, canGoBack, canGoForward,
    onBack, onForward, goTo, onEscAction, resetFilters, doUndo, doRedo,
    undoStackRef, redoStackRef, label, btnClass, toggleBtnClass,
  } = view

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
  const formatRiskValue = (value: number) => (riskSliderMax > 50 ? value.toFixed(0) : value.toFixed(2))
  const graphInfo = useMemo(() => {
    if (!activeProject) return 'Pick a project'
    if (!graph) return busy ? 'loading…' : '—'
    const shown = `${returnedNodes} Nodes · ${returnedEdges} Edges`
    const totalsDiffer =
      totalNodes != null && totalEdges != null &&
      (totalNodes !== returnedNodes || totalEdges !== returnedEdges || truncated || limitNodes != null)
    const totalPart = totalsDiffer
      ? ` (of ${totalNodes ?? '—'}/${totalEdges ?? '—'}${truncated ? ', truncated' : ''}${limitNodes ? `, limit ${limitNodes}` : ''})`
      : ''
    const statusSuffix = busy || stats.hydrating ? ' · loading…' : ''
    return `${shown}${totalPart}${statusSuffix}`
  }, [activeProject, graph, busy, returnedNodes, returnedEdges, totalNodes, totalEdges, truncated, limitNodes, stats.hydrating])
  const undoRedoControls = (
    <>
      <button type="button" className={btnClass} onClick={doUndo} disabled={!activeProject || undoStackRef.current.length === 0} title="Undo (Ctrl/⌘+Z)" aria-label="Undo (Ctrl/⌘+Z)">
        {label(<UndoIcon />, 'Z')}
      </button>
      <button type="button" className={btnClass} onClick={doRedo} disabled={!activeProject || redoStackRef.current.length === 0} title="Redo (Ctrl/⌘+Shift+Z)" aria-label="Redo (Ctrl/⌘+Shift+Z)">
        {label(<RedoIcon />, 'Y')}
      </button>
    </>
  )

  return (
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
  )
}
