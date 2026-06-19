import { useEffect } from 'react'
import type { MutableRefObject } from 'react'
import type { CytoscapeGraphActions } from './useCytoscapeGraph'

type Params = {
  focusGraph: boolean
  doUndo: () => void
  doRedo: () => void
  workspaceView: 'graph' | 'editor'
  selectedPath: string | null
  actionsRef: MutableRefObject<CytoscapeGraphActions | null>
  onNodeTap: (path: string) => void | Promise<void>
  onOpenFileEditor: (path: string) => void | Promise<void>
  onTogglePinSelected: () => void | Promise<void>
  onClearSelection: () => void
}

/**
 * Window-level keyboard shortcuts for the graph, extracted verbatim from
 * GraphCanvas. Two independent listeners:
 *   - undo/redo (Ctrl/Cmd+Z / Shift+Z / Y) while the graph is focused
 *   - node navigation (arrows), open (Enter), pin (P), hide (H) while the
 *     graph workspace view is active
 * Both bail out when a modal is open or the user is typing in a field.
 */
export function useGraphKeyboard({
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
}: Params) {
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
}
