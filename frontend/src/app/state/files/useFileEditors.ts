import { useCallback } from 'react'
import type { Dispatch, MutableRefObject, SetStateAction } from 'react'
import type { QueryClient } from '@tanstack/react-query'
import {
  getFileContent,
  updateFileContent,
  waitForTaskResult,
  TaskFailureError,
  type FileContent,
  type FileSaveResult,
  type Project,
} from '@/api'
import { extractError } from '@/shared/lib/errors'
import { safeStorageRemove, safeStorageSet } from '@/shared/lib/storage'
import {
  asStr,
  asWarnings,
  createFileEditorEntry,
  draftKey,
  getMutationTaskSeed,
  isEntryDirty,
  type DraftEntry,
  type FileEditorEntry,
  type FileSaveBanner,
  type PendingFileJump,
  type WorkspaceView,
} from '../internal'
import { useFileCloseFlow } from './useFileCloseFlow'
import { useNotifications } from '../session'
import { useWorkspace } from '../workspace'

const FILE_EDITOR_MAX_CHARS = 200_000

type Params = {
  queryClient: QueryClient
  draftPromptedRef: MutableRefObject<Set<string>>
}

/**
 * Owns the open-file editor tabs, drafts, save/close-with-confirm flows,
 * pending jumps/reloads and mutation indexing poll. Extracted verbatim from
 * useStubGraphApp; editor state is owned by the parent (it is reset on
 * selection change) and passed in along with selection/project deps.
 */
export function useFileEditors({
  queryClient,
  draftPromptedRef,
}: Params) {
  const { notifyInfo } = useNotifications()
  const ws = useWorkspace()
  const {
    activeProject, selectedOrgId, activeFilePath, openFilePaths, fileEditorsByPath,
    draftsByPath, draftRestore, confirmReason, pendingClosePath, pendingClosePaths,
    pendingActivePath, pendingReloadPath, pendingView, workspaceView,
  } = ws.state
  const {
    setActiveFilePath, setOpenFilePaths, setFileEditorsByPath, setDraftsByPath, setDraftRestore,
    setFileSaveBanner, setGraphStale, setGraphStaleMessage, setConfirmOpen, setConfirmReason,
    setPendingClosePath, setPendingClosePaths, setPendingActivePath, setPendingReloadPath,
    setPendingJump, setPendingView,
    setWorkspaceView: setWorkspaceViewState,
  } = ws.setters
  const updateFileEditorEntry = useCallback((path: string, updater: (entry: FileEditorEntry) => FileEditorEntry) => {
    const p = String(path || '').trim()
    if (!p) return
    setFileEditorsByPath((prev) => {
      const current = prev[p] ?? createFileEditorEntry(p)
      const next = updater(current)
      if (next === current) return prev
      return { ...prev, [p]: next }
    })
  }, [])

  const setActiveFileContent = useCallback(
    (value: string) => {
      if (!activeFilePath) return
      updateFileEditorEntry(activeFilePath, (entry) => {
        const nextContent = String(value ?? '')
        const dirty = nextContent !== entry.original
        return { ...entry, content: nextContent, dirty }
      })
    },
    [activeFilePath, updateFileEditorEntry],
  )

  const loadFileEditor = useCallback(
    async (path: string) => {
      if (!activeProject) return
      const p = String(path || '').trim()
      if (!p) return
      updateFileEditorEntry(p, (entry) => ({ ...entry, busy: true, error: null }))
      try {
        const res: FileContent = await getFileContent(activeProject.id, p, FILE_EDITOR_MAX_CHARS)
        const content = String(res.content ?? '')
        updateFileEditorEntry(p, (entry) => ({
          ...entry,
          content,
          original: content,
          dirty: false,
          truncated: Boolean(res.truncated),
          busy: false,
          saving: false,
          loaded: true,
          error: null,
        }))
        const draft = draftsByPath[p]
        if (draft && draft.content !== content && !draftPromptedRef.current.has(p)) {
          draftPromptedRef.current.add(p)
          setDraftRestore({ path: p, draft })
        }
      } catch (e: any) {
        updateFileEditorEntry(p, (entry) => ({
          ...entry,
          content: '',
          original: '',
          dirty: false,
          truncated: false,
          busy: false,
          saving: false,
          loaded: false,
          error: extractError(e),
        }))
      }
    },
    [activeProject, draftsByPath, updateFileEditorEntry],
  )

  const clearConfirm = useCallback(() => {
    setConfirmOpen(false)
    setConfirmReason(null)
    setPendingClosePath(null)
    setPendingClosePaths([])
    setPendingActivePath(null)
    setPendingReloadPath(null)
    setPendingView(null)
  }, [])

  const openFileEditor = useCallback(
    async (path: string) => {
      if (!activeProject) return
      const p = String(path || '').trim()
      if (!p) return
      setOpenFilePaths((prev) => (prev.includes(p) ? prev : [...prev, p]))
      setActiveFilePath(p)
      updateFileEditorEntry(p, (entry) => entry)
      const existingEntry = fileEditorsByPath[p]
      const shouldLoad = !existingEntry || (!existingEntry.loaded && !existingEntry.busy)
      if (shouldLoad) {
        await loadFileEditor(p)
      }
    },
    [activeProject, fileEditorsByPath, loadFileEditor, updateFileEditorEntry],
  )

  const openFileEditorAt = useCallback(
    async (path: string, line: number, column: number) => {
      if (!activeProject) return
      const p = String(path || '').trim()
      if (!p) return
      setPendingJump({
        path: p,
        line: Math.max(1, Math.trunc(line || 1)),
        column: Math.max(1, Math.trunc(column || 1)),
      })
      if (workspaceView !== 'editor') {
        setWorkspaceViewState('editor')
      }
      await openFileEditor(p)
    },
    [activeProject, openFileEditor, workspaceView],
  )

  const persistDrafts = useCallback(
    (next: Record<string, DraftEntry>) => {
      const pid = Number(activeProject?.id)
      if (!Number.isFinite(pid) || pid <= 0) return
      try {
        if (Object.keys(next).length > 0) {
          safeStorageSet(draftKey(pid), JSON.stringify(next))
        } else {
          safeStorageRemove(draftKey(pid))
        }
      } catch {}
    },
    [activeProject?.id],
  )

  const restoreDraft = useCallback(() => {
    if (!draftRestore) return
    const { path, draft } = draftRestore
    updateFileEditorEntry(path, (entry) => ({
      ...entry,
      content: draft.content,
      dirty: draft.content !== entry.original,
      error: null,
    }))
    setDraftRestore(null)
  }, [draftRestore, updateFileEditorEntry])

  const discardDraft = useCallback(() => {
    if (!draftRestore) return
    const { path } = draftRestore
    setDraftsByPath((prev) => {
      if (!(path in prev)) return prev
      const next = { ...prev }
      delete next[path]
      persistDrafts(next)
      return next
    })
    setDraftRestore(null)
  }, [draftRestore, persistDrafts])

  const clearDrafts = useCallback(() => {
    setDraftsByPath((prev) => {
      if (Object.keys(prev).length === 0) return prev
      persistDrafts({})
      return {}
    })
    setDraftRestore(null)
    draftPromptedRef.current = new Set()
  }, [persistDrafts])

  const clearPendingJump = useCallback(() => {
    setPendingJump(null)
  }, [])

  const requestReloadFileEditor = useCallback(async () => {
    if (!activeFilePath) return
    const activeEntry = fileEditorsByPath[activeFilePath]
    const activeDirty = isEntryDirty(activeEntry)
    if (activeDirty) {
      setConfirmOpen(true)
      setConfirmReason('reload-file')
      setPendingReloadPath(activeFilePath)
      setPendingClosePath(null)
      setPendingClosePaths([])
      setPendingActivePath(null)
      setPendingView(null)
      return
    }
    await loadFileEditor(activeFilePath)
  }, [activeFilePath, fileEditorsByPath, loadFileEditor])

  const queueMutationIndexingPoll = useCallback(
    (projectId: number, path: string, res: FileSaveResult | null | undefined, successMessage: string) => {
      notifyInfo(successMessage)
      const taskSeed = getMutationTaskSeed(res)
      if (!taskSeed) {
        setGraphStale(true)
        setGraphStaleMessage('Indexing task was not scheduled. Run a rescan manually.')
        return
      }

      setFileSaveBanner({
        path,
        status: 'rescan_scheduled',
        warnings: [],
        rescanTask: { task_id: taskSeed.task_id, status: taskSeed.status },
      })
      setGraphStale(true)
      setGraphStaleMessage('Indexing in progress…')

      void waitForTaskResult<Record<string, any>>(
        taskSeed,
        { pollIntervalMs: 1200, maxAttempts: 300 },
      )
        .then(async (result) => {
          const failed = Boolean(result?.aborted) || asStr(result?.index_status) === 'failed'
          if (failed) {
            const error = asStr(result?.error) || 'Indexing failed.'
            setFileSaveBanner({
              path,
              status: 'failed',
              warnings: asWarnings(result?.warnings),
              error,
              metricsPending: Boolean(result?.metrics_pending),
            })
            setGraphStale(true)
            setGraphStaleMessage(error)
            return
          }

          setFileSaveBanner(null)
          setGraphStale(false)
          setGraphStaleMessage(null)
          await Promise.all([
            queryClient.invalidateQueries({ queryKey: ['graph', selectedOrgId, projectId] }),
            queryClient.invalidateQueries({ queryKey: ['node', selectedOrgId, projectId] }),
            queryClient.invalidateQueries({ queryKey: ['files', selectedOrgId, projectId] }),
          ])
        })
        .catch((e: any) => {
          const taskFailure = e instanceof TaskFailureError ? e : null
          const structured = taskFailure?.errorPayload
          const error = taskFailure
            ? `${structured?.code ?? 'task_failed'}${structured?.stage ? ` (${structured.stage})` : ''}: ${structured?.message ?? taskFailure.message}`
            : extractError(e)
          setFileSaveBanner({
            path,
            status: 'failed',
            warnings: ['scan_failed'],
            error,
          })
          setGraphStale(true)
          setGraphStaleMessage(error)
        })
    },
    [notifyInfo, queryClient, selectedOrgId],
  )


  const saveFileEditorPath = useCallback(async (path: string): Promise<boolean> => {
    if (!activeProject) return false
    const p = String(path || '').trim()
    if (!p) return false
    const entry = fileEditorsByPath[p]
    if (!entry) return false
    updateFileEditorEntry(p, (current) => ({ ...current, saving: true, error: null }))
    try {
      const res: FileSaveResult = await updateFileContent(activeProject.id, p, entry.content)
      if (!res?.saved) return false

      updateFileEditorEntry(p, (current) => ({
        ...current,
        original: current.content,
        dirty: false,
        truncated: false,
      }))
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['graph', selectedOrgId, activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['node', selectedOrgId, activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['files', selectedOrgId, activeProject.id] }),
      ])
      queueMutationIndexingPoll(activeProject.id, p, res, 'File saved')
      return true
    } catch (e: any) {
      updateFileEditorEntry(p, (current) => ({ ...current, error: extractError(e) }))
    } finally {
      updateFileEditorEntry(p, (current) => ({ ...current, saving: false }))
    }
    return false
  }, [
    activeProject,
    fileEditorsByPath,
    queryClient,
    queueMutationIndexingPoll,
    selectedOrgId,
    updateFileEditorEntry,
  ])

  const saveFileEditor = useCallback(async (): Promise<boolean> => {
    if (!activeFilePath) return false
    return saveFileEditorPath(activeFilePath)
  }, [activeFilePath, saveFileEditorPath])

  const saveAllOpenFiles = useCallback(async (): Promise<boolean> => {
    const dirtyPaths = openFilePaths.filter((path) => {
      const entry = fileEditorsByPath[path]
      return entry ? entry.dirty : false
    })
    if (dirtyPaths.length === 0) return false
    const results = await Promise.all(dirtyPaths.map((path) => saveFileEditorPath(path)))
    return results.every(Boolean)
  }, [fileEditorsByPath, openFilePaths, saveFileEditorPath])

  const closeFlow = useFileCloseFlow({
    activeFilePath, confirmReason, fileEditorsByPath, pendingClosePath, pendingClosePaths,
    pendingActivePath, pendingReloadPath, pendingView, setActiveFilePath, setOpenFilePaths,
    setFileEditorsByPath, setPendingReloadPath, setWorkspaceViewState, clearConfirm,
    updateFileEditorEntry, loadFileEditor, openFileEditor, saveFileEditorPath,
  })

  return {
    ...closeFlow,
    updateFileEditorEntry,
    setActiveFileContent,
    loadFileEditor,
    clearConfirm,
    openFileEditor,
    openFileEditorAt,
    persistDrafts,
    restoreDraft,
    discardDraft,
    clearDrafts,
    clearPendingJump,
    requestReloadFileEditor,
    queueMutationIndexingPoll,
    saveFileEditorPath,
    saveFileEditor,
    saveAllOpenFiles,
  }
}
