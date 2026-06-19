import { useCallback, useEffect, useRef } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import type { GraphData } from '@/api'
import { isAnyModalOpen } from './useStubGraphApp.internal'
import type { WorkspaceView } from './useStubGraphApp.internal'

type Params = {
  canGoBack: boolean
  canGoForward: boolean
  goBack: () => void
  goForward: () => void
  paletteOpen: boolean
  setPaletteOpen: Dispatch<SetStateAction<boolean>>
  focusGraph: boolean
  setFocusGraph: Dispatch<SetStateAction<boolean>>
  selectedPath: string | null
  onClearSelection: () => void
  onFocusSearch?: () => void
  workspaceView: WorkspaceView
  toggleWorkspaceView: () => void
  graph: GraphData | null
  leftPanelOpen: boolean
  rightPanelOpen: boolean
  setLeftPanelOpen: Dispatch<SetStateAction<boolean>>
  setRightPanelOpen: Dispatch<SetStateAction<boolean>>
  toggleLeftPanel: () => void
  toggleRightPanel: () => void
  toggleCompactMode: () => void
  fileEditorOpen: boolean
  activeFilePath: string | null
  openFilePaths: string[]
  openFileEditor: (path: string) => void | Promise<void>
  requestFindInFile: () => void
  requestReplaceInFile: () => void
  requestOutlineInFile: () => void
  setGotoLineRequestId: Dispatch<SetStateAction<number>>
}

/**
 * Global window keyboard shortcuts (command palette, find/replace/outline,
 * tab cycling, undo/redo delegation, panel + focus toggles, history nav).
 * Extracted verbatim from useStubGraphApp; owns the undo/redo handler ref and
 * exposes registerUndoRedoHandlers for the graph to register into.
 */
export function useGlobalKeyboard({
  canGoBack,
  canGoForward,
  goBack,
  goForward,
  paletteOpen,
  setPaletteOpen,
  focusGraph,
  setFocusGraph,
  selectedPath,
  onClearSelection,
  onFocusSearch,
  workspaceView,
  toggleWorkspaceView,
  graph,
  leftPanelOpen,
  rightPanelOpen,
  setLeftPanelOpen,
  setRightPanelOpen,
  toggleLeftPanel,
  toggleRightPanel,
  toggleCompactMode,
  fileEditorOpen,
  activeFilePath,
  openFilePaths,
  openFileEditor,
  requestFindInFile,
  requestReplaceInFile,
  requestOutlineInFile,
  setGotoLineRequestId,
}: Params) {
  const undoRedoHandlersRef = useRef<{ undo?: () => void; redo?: () => void } | null>(null)

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
      if (mod && e.shiftKey && !e.altKey && (e.key === 'p' || e.key === 'P')) {
        if (otherModalOpen) return
        e.preventDefault()
        setPaletteOpen(true)
        return
      }

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

      if (mod && !e.altKey && e.key === 'Tab') {
        if (!fileEditorOpen) return
        if (!activeFilePath || openFilePaths.length === 0) return
        const currentIndex = openFilePaths.indexOf(activeFilePath)
        if (currentIndex < 0) return
        const nextIndex = e.shiftKey
          ? (currentIndex - 1 + openFilePaths.length) % openFilePaths.length
          : (currentIndex + 1) % openFilePaths.length
        const nextPath = openFilePaths[nextIndex]
        if (!nextPath) return
        e.preventDefault()
        void openFileEditor(nextPath)
        return
      }

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
      if (!otherModalOpen && !typing && workspaceView === 'graph' && (e.key === 'f' || e.key === 'F')) {
        setFocusGraph((v) => !v)
      }
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
    activeFilePath,
    openFilePaths,
    openFileEditor,
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

  return { registerUndoRedoHandlers }
}
