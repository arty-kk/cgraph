import React from 'react'
import type { Project } from '@/api'
import type { CytoscapeGraphActions, GraphEditSnapshot } from '../hooks/useCytoscapeGraph'
import { baseName } from '../lib/GraphCanvas.helpers'
import { EyeIcon, FilterIcon, LockIcon, ResetLayoutIcon, SaveLayoutIcon } from './GraphCanvas.icons'

type Props = {
  activeProject: Project | null
  graphMode: 'local' | 'full' | 'limit'
  visibleNodes: number
  returnedNodes: number
  returnedEdges: number
  selectedPath: string | null
  editStats: ReturnType<CytoscapeGraphActions['getEditStats']>
  filtersActiveCount: number
  compactMode: boolean
  hoverRevealFlex: string
  btnClass: string
  label: (icon: React.ReactNode, hotkey?: string) => React.ReactNode
  actions: CytoscapeGraphActions
  onOpenPanel: () => void
  pushUndo: (snap: GraphEditSnapshot | null) => void
  notifyInfo: (message: string) => void
  saveLayout: () => void
  resetLayout: () => void
}

export function GraphStatusBar({
  activeProject,
  graphMode,
  visibleNodes,
  returnedNodes,
  returnedEdges,
  selectedPath,
  editStats,
  filtersActiveCount,
  compactMode,
  hoverRevealFlex,
  btnClass,
  label,
  actions,
  onOpenPanel,
  pushUndo,
  notifyInfo,
  saveLayout,
  resetLayout,
}: Props) {
  if (!activeProject) return null
  return (
    <div className="absolute bottom-3 right-3 z-10 flex max-w-[calc(100%-24px)] flex-wrap items-end gap-2">
      <div className="group max-w-[calc(100%-24px)] rounded-md bg-neutral-950/80 border border-neutral-800 px-3 py-2 shadow-lg text-[11px] text-neutral-300 break-words">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-neutral-400">Mode:</span> <span className="text-neutral-100 font-semibold">{graphMode}</span>
          <span className="text-neutral-500">·</span>
          <span>Nodes: <span className="text-neutral-100">{visibleNodes}</span>/{returnedNodes}</span>
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
              onClick={() => onOpenPanel()}
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
  )
}
