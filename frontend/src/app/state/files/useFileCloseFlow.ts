import { useCallback } from 'react'
import type { FileEditorEntry } from '../internal'
import { useWorkspace } from '../workspace'

type Params = {
  clearConfirm: () => void
  updateFileEditorEntry: (path: string, updater: (entry: FileEditorEntry) => FileEditorEntry) => void
  loadFileEditor: (path: string) => Promise<void> | void
  openFileEditor: (path: string) => Promise<void> | void
  saveFileEditorPath: (path: string) => Promise<boolean>
}

/**
 * Close-tab / save / discard / cancel flows for the file editor confirm
 * dialog (close one or many tabs, optionally saving or reloading first).
 * Extracted verbatim from useFileEditors.
 */
export function useFileCloseFlow({
  clearConfirm,
  updateFileEditorEntry,
  loadFileEditor,
  openFileEditor,
  saveFileEditorPath,
}: Params) {
  const ws = useWorkspace()
  const {
    activeFilePath, confirmReason, fileEditorsByPath, pendingClosePath, pendingClosePaths,
    pendingActivePath, pendingReloadPath, pendingView,
  } = ws.state
  const {
    setActiveFilePath, setOpenFilePaths, setFileEditorsByPath, setPendingReloadPath,
    setWorkspaceView: setWorkspaceViewState,
  } = ws.setters
  const closeFileEditorPaths = useCallback((paths: string[]) => {
    if (paths.length === 0) return
    const closingSet = new Set(paths)
    setOpenFilePaths((prev) => {
      if (!prev.some((item) => closingSet.has(item))) return prev
      const next = prev.filter((item) => !closingSet.has(item))
      if (activeFilePath && closingSet.has(activeFilePath)) {
        const activeIndex = prev.indexOf(activeFilePath)
        let nextActive: string | null = null
        for (let i = activeIndex + 1; i < prev.length; i += 1) {
          const candidate = prev[i]
          if (!closingSet.has(candidate)) {
            nextActive = candidate
            break
          }
        }
        if (!nextActive) {
          for (let i = activeIndex - 1; i >= 0; i -= 1) {
            const candidate = prev[i]
            if (!closingSet.has(candidate)) {
              nextActive = candidate
              break
            }
          }
        }
        setActiveFilePath(nextActive)
      }
      return next
    })
    setFileEditorsByPath((prev) => {
      let changed = false
      const next = { ...prev }
      for (const path of closingSet) {
        if (path in next) {
          delete next[path]
          changed = true
        }
      }
      return changed ? next : prev
    })
  }, [activeFilePath])

  const confirmSave = useCallback(async () => {
    const pendingTargets = pendingClosePaths.length
      ? pendingClosePaths
      : pendingClosePath
        ? [pendingClosePath]
        : activeFilePath
          ? [activeFilePath]
          : []
    const pendingDirtyTargets = pendingTargets.filter((path) => {
      const entry = fileEditorsByPath[path]
      return entry ? entry.dirty : false
    })
    const hasBusyTarget = pendingTargets.some((path) => {
      const entry = fileEditorsByPath[path]
      return entry ? entry.saving || entry.busy : false
    })
    if (hasBusyTarget) return
    const results = await Promise.all(pendingDirtyTargets.map((path) => saveFileEditorPath(path)))
    const saved = pendingDirtyTargets.length === 0 ? true : results.every(Boolean)
    if (!saved) return
    if (pendingClosePaths.length > 0) {
      closeFileEditorPaths(pendingClosePaths)
    } else if (pendingClosePath) {
      closeFileEditorPaths([pendingClosePath])
    } else if (pendingActivePath) {
      await openFileEditor(pendingActivePath)
    } else if (pendingView) {
      setWorkspaceViewState(pendingView)
    }
    clearConfirm()
  }, [
    clearConfirm,
    closeFileEditorPaths,
    openFileEditor,
    pendingActivePath,
    pendingClosePath,
    pendingClosePaths,
    pendingView,
    saveFileEditorPath,
    activeFilePath,
    fileEditorsByPath,
  ])

  const confirmDiscard = useCallback(async () => {
    if (confirmReason === 'reload-file') {
      const targetPath = pendingReloadPath ?? activeFilePath
      const targetEntry = targetPath ? fileEditorsByPath[targetPath] : null
      if (targetEntry?.saving || targetEntry?.busy) return
      if (targetPath) {
        await loadFileEditor(targetPath)
      }
      setPendingReloadPath(null)
      clearConfirm()
      return
    }
    const pendingTargets = pendingClosePaths.length
      ? pendingClosePaths
      : pendingClosePath
        ? [pendingClosePath]
        : activeFilePath
          ? [activeFilePath]
          : []
    const hasBusyTarget = pendingTargets.some((path) => {
      const entry = fileEditorsByPath[path]
      return entry ? entry.saving || entry.busy : false
    })
    if (hasBusyTarget) return
    pendingTargets.forEach((path) => {
      updateFileEditorEntry(path, (entry) => {
        if (!entry.dirty) return entry
        return { ...entry, content: entry.original, dirty: false, error: null }
      })
    })
    if (pendingClosePaths.length > 0) {
      closeFileEditorPaths(pendingClosePaths)
    } else if (pendingClosePath) {
      closeFileEditorPaths([pendingClosePath])
    } else if (pendingActivePath) {
      await openFileEditor(pendingActivePath)
    } else if (pendingView) {
      setWorkspaceViewState(pendingView)
    }
    clearConfirm()
  }, [
    clearConfirm,
    closeFileEditorPaths,
    confirmReason,
    fileEditorsByPath,
    loadFileEditor,
    openFileEditor,
    pendingActivePath,
    pendingClosePath,
    pendingClosePaths,
    pendingReloadPath,
    pendingView,
    activeFilePath,
    updateFileEditorEntry,
  ])

  const confirmCancel = useCallback(() => {
    const pendingTargets = pendingClosePaths.length
      ? pendingClosePaths
      : pendingClosePath
        ? [pendingClosePath]
        : activeFilePath
          ? [activeFilePath]
          : []
    const hasBusyTarget = pendingTargets.some((path) => {
      const entry = fileEditorsByPath[path]
      return entry ? entry.saving || entry.busy : false
    })
    if (hasBusyTarget) return
    clearConfirm()
  }, [activeFilePath, clearConfirm, fileEditorsByPath, pendingClosePath, pendingClosePaths])

  return { closeFileEditorPaths, confirmSave, confirmDiscard, confirmCancel }
}
