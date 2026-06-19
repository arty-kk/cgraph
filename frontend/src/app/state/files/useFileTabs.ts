import { useCallback } from 'react'
import type { Dispatch, MutableRefObject, SetStateAction } from 'react'
import {
  isEntryDirty,
  type FileEditorEntry,
  type WorkspaceView,
} from '../internal'

type Params = {
  activeFilePath: string | null
  openFilePaths: string[]
  fileEditorsByPath: Record<string, FileEditorEntry>
  workspaceView: WorkspaceView
  selectedPathRef: MutableRefObject<string | null>
  closeFileEditorPaths: (paths: string[]) => void
  openFileEditor: (path: string) => void | Promise<void>
  setSelection: (nextRaw: string | null, opts?: { pushHistory?: boolean }) => void
  setConfirmOpen: Dispatch<SetStateAction<boolean>>
  setConfirmReason: Dispatch<SetStateAction<string | null>>
  setPendingClosePath: Dispatch<SetStateAction<string | null>>
  setPendingClosePaths: Dispatch<SetStateAction<string[]>>
  setPendingActivePath: Dispatch<SetStateAction<string | null>>
  setPendingView: Dispatch<SetStateAction<WorkspaceView | null>>
  setWorkspaceViewState: Dispatch<SetStateAction<WorkspaceView>>
  setFindRequestId: Dispatch<SetStateAction<number>>
  setReplaceRequestId: Dispatch<SetStateAction<number>>
  setOutlineRequestId: Dispatch<SetStateAction<number>>
}

/**
 * Tab management (close tab / all / others / to-right with dirty-confirm) and
 * the workspace view toggle + find/replace/outline request bumps. Extracted
 * verbatim from useStubGraphApp.
 */
export function useFileTabs({
  activeFilePath,
  openFilePaths,
  fileEditorsByPath,
  workspaceView,
  selectedPathRef,
  closeFileEditorPaths,
  openFileEditor,
  setSelection,
  setConfirmOpen,
  setConfirmReason,
  setPendingClosePath,
  setPendingClosePaths,
  setPendingActivePath,
  setPendingView,
  setWorkspaceViewState,
  setFindRequestId,
  setReplaceRequestId,
  setOutlineRequestId,
}: Params) {
  const closeFileEditor = useCallback(
    (path: string) => {
      const p = String(path || '').trim()
      if (!p) return
      const entry = fileEditorsByPath[p]
      const isDirty = isEntryDirty(entry)
      if (isDirty) {
        setConfirmOpen(true)
        setConfirmReason('close-tab')
        setPendingClosePath(p)
        setPendingClosePaths([])
        setPendingActivePath(null)
        setPendingView(null)
        return
      }
      closeFileEditorPaths([p])
    },
    [closeFileEditorPaths, fileEditorsByPath],
  )

  const closeAllTabs = useCallback(() => {
    if (openFilePaths.length === 0) return
    const dirtyPaths = openFilePaths.filter((path) => {
      const entry = fileEditorsByPath[path]
      return isEntryDirty(entry)
    })
    if (dirtyPaths.length > 0) {
      setConfirmOpen(true)
      setConfirmReason('close-tab')
      setPendingClosePaths(openFilePaths)
      setPendingClosePath(null)
      setPendingActivePath(null)
      setPendingView(null)
      return
    }
    closeFileEditorPaths(openFilePaths)
  }, [closeFileEditorPaths, fileEditorsByPath, openFilePaths])

  const closeOtherTabs = useCallback((targetPath: string | null) => {
    const activePath = String(targetPath || '').trim()
    if (!activePath) return
    const targets = openFilePaths.filter((path) => path !== activePath)
    if (targets.length === 0) return
    const dirtyPaths = targets.filter((path) => {
      const entry = fileEditorsByPath[path]
      return isEntryDirty(entry)
    })
    if (dirtyPaths.length > 0) {
      setConfirmOpen(true)
      setConfirmReason('close-tab')
      setPendingClosePaths(targets)
      setPendingClosePath(null)
      setPendingActivePath(null)
      setPendingView(null)
      return
    }
    closeFileEditorPaths(targets)
  }, [closeFileEditorPaths, fileEditorsByPath, openFilePaths])

  const closeTabsToRight = useCallback((targetPath: string | null) => {
    const activePath = String(targetPath || '').trim()
    if (!activePath) return
    const activeIndex = openFilePaths.indexOf(activePath)
    if (activeIndex < 0 || activeIndex >= openFilePaths.length - 1) return
    const targets = openFilePaths.slice(activeIndex + 1)
    if (targets.length === 0) return
    const dirtyPaths = targets.filter((path) => {
      const entry = fileEditorsByPath[path]
      return isEntryDirty(entry)
    })
    if (dirtyPaths.length > 0) {
      setConfirmOpen(true)
      setConfirmReason('close-tab')
      setPendingClosePaths(targets)
      setPendingClosePath(null)
      setPendingActivePath(null)
      setPendingView(null)
      return
    }
    closeFileEditorPaths(targets)
  }, [closeFileEditorPaths, fileEditorsByPath, openFilePaths])

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
        setPendingClosePaths([])
        setPendingActivePath(null)
        return
      }
      setWorkspaceViewState(nextView)
      if (nextView === 'graph' && activeFilePath) {
        setSelection(activeFilePath, { pushHistory: false })
      }
      const nextPath = selectedPathRef.current
      if (nextView === 'editor' && nextPath && nextPath !== activeFilePath) {
        void openFileEditor(nextPath)
      }
    },
    [activeFilePath, fileEditorsByPath, openFileEditor, setSelection, workspaceView],
  )

  const toggleWorkspaceView = useCallback(() => {
    setWorkspaceView(workspaceView === 'graph' ? 'editor' : 'graph')
  }, [setWorkspaceView, workspaceView])

  const requestFindInFile = useCallback(() => {
    setFindRequestId((value) => value + 1)
  }, [])

  const requestReplaceInFile = useCallback(() => {
    setReplaceRequestId((value) => value + 1)
  }, [])

  const requestOutlineInFile = useCallback(() => {
    setOutlineRequestId((value) => value + 1)
  }, [])


  return {
    closeFileEditor,
    closeAllTabs,
    closeOtherTabs,
    closeTabsToRight,
    setWorkspaceView,
    toggleWorkspaceView,
    requestFindInFile,
    requestReplaceInFile,
    requestOutlineInFile,
  }
}
