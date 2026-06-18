import React from 'react'
import type { GraphData } from '@/api'
import type { CytoscapeGraphActions, GraphEditSnapshot } from './useCytoscapeGraph'
import { baseName } from './GraphCanvas.helpers'

type CtxMenuState = { path: string; x: number; y: number }

type Props = {
  ctxMenu: CtxMenuState | null
  menuRef: React.Ref<HTMLDivElement>
  ctxNode: GraphData['nodes'][number] | null
  ctxPinned: boolean
  selectedPath: string | null
  actions: CytoscapeGraphActions
  onClose: () => void
  onOpenNeighbors: () => void
  onTogglePinPath: (path: string) => void | Promise<void>
  onOpenFileEditor: (path: string) => void | Promise<void>
  onQuickSummary: (path: string) => void | Promise<void>
  onClearSelection: () => void
  pushUndo: (snap: GraphEditSnapshot | null) => void
  saveLayout: () => void
  resetLayout: () => void
  notifyInfo: (message: string) => void
  quickSummaryTitleFor: (path: string) => string
  isQuickSummaryDisabledFor: (path: string) => boolean
}

export function GraphContextMenu({
  ctxMenu,
  menuRef,
  ctxNode,
  ctxPinned,
  selectedPath,
  actions,
  onClose,
  onOpenNeighbors,
  onTogglePinPath,
  onOpenFileEditor,
  onQuickSummary,
  onClearSelection,
  pushUndo,
  saveLayout,
  resetLayout,
  notifyInfo,
  quickSummaryTitleFor,
  isQuickSummaryDisabledFor,
}: Props) {
  if (!ctxMenu) return null
  return (
    <div
      ref={menuRef}
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
          onClick={() => { actions.centerPath(ctxMenu.path); onClose() }}
        >
          Center
        </button>
        <button
          type="button"
          className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
          onClick={async () => { await Promise.resolve(onTogglePinPath(ctxMenu.path)); onClose() }}
        >
          {ctxPinned ? 'Unpin' : 'Pin'}
        </button>
        <button
          type="button"
          className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
          onClick={() => { void Promise.resolve(onOpenFileEditor(ctxMenu.path)); onClose() }}
        >
          Open in editor
        </button>
        <button
          type="button"
          className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold disabled:opacity-50"
          onClick={() => { void Promise.resolve(onQuickSummary(ctxMenu.path)); onClose() }}
          title={quickSummaryTitleFor(ctxMenu.path)}
          disabled={isQuickSummaryDisabledFor(ctxMenu.path)}
        >
          Quick summary
        </button>
        <button
          type="button"
          className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
          onClick={() => { pushUndo(actions.exportSnapshot()); actions.toggleLockPath(ctxMenu.path); onClose(); notifyInfo('Lock toggled') }}
          title="Lock/unlock node position (freeze)"
        >
          Lock/Unlock
        </button>
        <button
          type="button"
          className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
          onClick={() => { pushUndo(actions.exportSnapshot()); actions.unlockAll(); onClose(); notifyInfo('Unlocked all') }}
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
            onClose()
            notifyInfo('Node hidden')
          }}
          title="Hide node"
        >
          Hide node
        </button>
        <button
          type="button"
          className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
          onClick={() => { pushUndo(actions.exportSnapshot()); actions.hideOthers(ctxMenu.path); onClose(); notifyInfo('Others hidden') }}
          title="Keep only node neighborhood"
        >
          Hide Others
        </button>

        <button
          type="button"
          className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
          onClick={() => { pushUndo(actions.exportSnapshot()); actions.showAll(); onClose(); notifyInfo('Show all') }}
          title="Show all hidden nodes"
        >
          Show All
        </button>
        <button
          type="button"
          className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
          onClick={() => { pushUndo(actions.exportSnapshot()); actions.relayoutVisible(); onClose(); notifyInfo('Relayout visible') }}
          title="Relayout only visible nodes"
        >
          Relayout visible
        </button>

        <button
          type="button"
          className="rounded-md bg-neutral-800 hover:bg-neutral-700 px-2 py-1 text-[11px] font-semibold"
          onClick={() => { saveLayout(); onClose() }}
          title="Save layout"
        >
          Save layout
        </button>
        <button
          type="button"
          className="rounded-md bg-neutral-800 hover:bg-neutral-700 px-2 py-1 text-[11px] font-semibold"
          onClick={() => { resetLayout(); onClose() }}
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
            onClose()
          }}
        >
          Copy Path
        </button>
        <button
          type="button"
          className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
          onClick={() => { onOpenNeighbors(); onClose() }}
          disabled={!ctxMenu.path}
        >
          Neighbors
        </button>
        <button
          type="button"
          className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
          onClick={() => { actions.fit(); onClose() }}
        >
          Fit
        </button>
        <button
          type="button"
          className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
          onClick={() => { actions.relayout(); onClose() }}
        >
          Relayout
        </button>
      </div>
    </div>
  )
}
