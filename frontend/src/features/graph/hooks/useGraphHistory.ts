import { useCallback, useEffect, useRef, useState } from 'react'
import type { MutableRefObject } from 'react'
import type { CytoscapeGraphActions, GraphEditSnapshot } from './useCytoscapeGraph'

type Params = {
  /** Shared ref to the live cytoscape actions (owned by GraphCanvas). */
  actionsRef: MutableRefObject<CytoscapeGraphActions | null>
  /** Shared ref to the toast/notify function (owned by GraphCanvas). */
  notifyRef: MutableRefObject<(msg: string) => void>
  onRegisterUndoRedo?: (handlers: { undo: () => void; redo: () => void }) => void
}

/**
 * Owns the graph edit undo/redo stacks and the drag-snapshot ref. Extracted
 * verbatim from GraphCanvas. actionsRef/notifyRef stay owned by GraphCanvas
 * (used widely elsewhere) and are passed in. The returned refs are read by
 * the drag handlers and the toolbar's disabled states.
 */
export function useGraphHistory({
  actionsRef,
  notifyRef,
  onRegisterUndoRedo,
}: Params) {
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

  // Clear both stacks and force a re-render so toolbar disabled states update.
  // Called from GraphCanvas's project/instance/graph-change effect.
  const clearHistory = useCallback(() => {
    undoStackRef.current = []
    redoStackRef.current = []
    dragBeforeRef.current = null
    forceRerender((x) => x + 1)
  }, [])

  useEffect(() => {
    onRegisterUndoRedo?.({ undo: doUndo, redo: doRedo })
    return () => {
      onRegisterUndoRedo?.({ undo: () => {}, redo: () => {} })
    }
  }, [doRedo, doUndo, onRegisterUndoRedo])

  return { undoStackRef, redoStackRef, dragBeforeRef, pushUndo, doUndo, doRedo, clearHistory }
}
