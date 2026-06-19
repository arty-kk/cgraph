import React from 'react'
import type { MutableRefObject } from 'react'
import type { GraphData, Project } from '@/api'
import { EyeIcon, SummaryIcon } from './GraphCanvas.icons'

/** Bottom-left banner shown while a large graph hydrates in batches. */
export function GraphLoadingBanner({
  hydrating,
  pinnedCount,
  compactMode,
}: {
  hydrating: boolean
  pinnedCount: number
  compactMode: boolean
}) {
  if (!hydrating) return null
  return (
    <div
      className="absolute left-3 z-10 rounded-md bg-neutral-950/80 border border-neutral-800 px-3 py-2 text-[11px] text-neutral-300 shadow-lg"
      style={{ bottom: pinnedCount ? 220 : 12 }}
    >
      {compactMode ? 'Loading…' : 'Loading a large graph in batches to avoid freezing the browser…'}
    </div>
  )
}

/** Bottom-right banner shown when the graph is truncated or top-N limited. */
export function GraphLimitBanner({
  show,
  activeProject,
  truncated,
  limitNodes,
  returnedNodes,
  totalNodes,
  compactMode,
  hoverRevealBlock,
}: {
  show: boolean
  activeProject: Project | null
  truncated: boolean
  limitNodes: number | null
  returnedNodes: number
  totalNodes: number | null
  compactMode: boolean
  hoverRevealBlock: string
}) {
  if (!show) return null
  return (
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
  )
}

/** Centered hint shown when a project is selected but no graph is rendered yet. */
export function GraphEmptyState({
  activeProject,
  graph,
  busy,
  graphMode,
  selectedPath,
  onOpenPalette,
  onScan,
  onRefresh,
}: {
  activeProject: Project | null
  graph: GraphData | null
  busy: boolean
  graphMode: 'local' | 'full' | 'limit'
  selectedPath: string | null
  onOpenPalette: () => void
  onScan: () => void | Promise<void>
  onRefresh: () => void | Promise<void>
}) {
  if (!activeProject || graph || busy) return null
  return (
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
  )
}

/** Floating view/summary buttons anchored to the selected node. */
export function GraphFileButtons({
  fileButtonPos,
  selectedPath,
  activeProject,
  selectedInGraph,
  fileButtonsRef,
  onOpenFileEditor,
  onQuickSummary,
  quickSummaryTitleFor,
  isQuickSummaryDisabledFor,
}: {
  fileButtonPos: { x: number; y: number } | null
  selectedPath: string | null
  activeProject: Project | null
  selectedInGraph: boolean
  fileButtonsRef: MutableRefObject<HTMLDivElement | null>
  onOpenFileEditor: (path: string) => void | Promise<void>
  onQuickSummary: (path: string) => void | Promise<void>
  quickSummaryTitleFor: (path: string) => string
  isQuickSummaryDisabledFor: (path: string) => boolean
}) {
  if (!fileButtonPos || !selectedPath || !activeProject || !selectedInGraph) return null
  return (
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
  )
}
