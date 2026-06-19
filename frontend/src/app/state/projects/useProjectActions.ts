import { useCallback } from 'react'
import type { Dispatch, MutableRefObject, SetStateAction } from 'react'
import type { QueryClient } from '@tanstack/react-query'
import {
  createFile,
  createProjectFromRoot,
  createProjectFromSnapshot,
  deleteFile,
  deleteProject,
  listProjects,
  renameFile,
  scanProjectStatus,
  isTaskStatus,
  waitForTaskResult,
  type Project,
  type SnapshotCreateTaskResult,
  type FileSaveResult,
} from '@/api'
import { safeStorageRemove } from '@/shared/lib/storage'
import {
  pickCreatedSnapshotProject,
  wsKey,
  type FileEditorEntry,
  type FileSaveBanner,
} from '../internal'
import { useTaskTracking } from '../session'

type Params = {
  activeProject: Project | null
  allowLocalRootPath: boolean | null
  newName: string
  newArchive: File | null
  newPath: string
  selectedOrgId: number | null
  selectedPathRef: MutableRefObject<string | null>
  projectsQuery: { data: Project[] | undefined }
  queryClient: QueryClient
  runOp: (fn: () => Promise<void>) => Promise<void>
  runOpThrow: (fn: () => Promise<void>) => Promise<void>
  selectProjectLocal: (p: Project) => void
  clearActiveProject: () => void
  queueMutationIndexingPoll: (
    projectId: number,
    path: string,
    res: FileSaveResult | null | undefined,
    successMessage: string,
  ) => void
  setSelection: (nextRaw: string | null, opts?: { pushHistory?: boolean }) => void
  setNewArchive: Dispatch<SetStateAction<File | null>>
  setNewPath: Dispatch<SetStateAction<string>>
  setPinnedPaths: Dispatch<SetStateAction<string[]>>
  setActiveFilePath: Dispatch<SetStateAction<string | null>>
  setOpenFilePaths: Dispatch<SetStateAction<string[]>>
  setFileEditorsByPath: Dispatch<SetStateAction<Record<string, FileEditorEntry>>>
  setFileSaveBanner: Dispatch<SetStateAction<FileSaveBanner | null>>
  setGraphStale: Dispatch<SetStateAction<boolean>>
  setGraphStaleMessage: Dispatch<SetStateAction<string | null>>
}

/**
 * Project + file mutation operations: pick/create/delete project, scan,
 * refresh, and create/rename/delete file (each wired through runOp and the
 * mutation indexing poll). Extracted verbatim from useStubGraphApp.
 */
export function useProjectActions({
  activeProject,
  allowLocalRootPath,
  newName,
  newArchive,
  newPath,
  selectedOrgId,
  selectedPathRef,
  projectsQuery,
  queryClient,
  runOp,
  runOpThrow,
  selectProjectLocal,
  clearActiveProject,
  queueMutationIndexingPoll,
  setSelection,
  setNewArchive,
  setNewPath,
  setPinnedPaths,
  setActiveFilePath,
  setOpenFilePaths,
  setFileEditorsByPath,
  setFileSaveBanner,
  setGraphStale,
  setGraphStaleMessage,
}: Params) {
  const { trackTaskStatus } = useTaskTracking()
  const onPickProject = useCallback((p: Project) => selectProjectLocal(p), [selectProjectLocal])

  const onCreateProject = useCallback(async () => {
    await runOp(async () => {
      const name = newName.trim()
      if (newArchive) {
        const initial = await createProjectFromSnapshot(name, newArchive)
        if (isTaskStatus(initial)) {
          trackTaskStatus(initial, 'scan', `Snapshot import ${name}`)
        }
        const taskResult = await waitForTaskResult<SnapshotCreateTaskResult>(initial, {
          pollIntervalMs: 1200,
          maxAttempts: 300,
        })
        setNewArchive(null)
        await queryClient.invalidateQueries({ queryKey: ['projects', selectedOrgId] })
        const refreshedProjects = await queryClient.fetchQuery<Project[]>({
          queryKey: ['projects', selectedOrgId],
          queryFn: listProjects,
        })
        const created = pickCreatedSnapshotProject(refreshedProjects ?? [], taskResult)
        if (!created) {
          throw new Error('Snapshot import completed, but created project was not found after refresh.')
        }
        selectProjectLocal(created)
        return
      }
      const root = newPath.trim()
      if (!root) {
        throw new Error('Укажи архив или root_path')
      }
      if (allowLocalRootPath === false) {
        throw new Error('Local root_path is disabled on this server')
      }
      const p = await createProjectFromRoot(name, root)
      selectProjectLocal(p)
      setNewPath('')
      await queryClient.invalidateQueries({ queryKey: ['projects', selectedOrgId] })
    })
  }, [
    allowLocalRootPath,
    newArchive,
    newName,
    newPath,
    queryClient,
    runOp,
    trackTaskStatus,
    selectedOrgId,
    selectProjectLocal,
    setNewArchive,
    setNewPath,
  ])

  const onDeleteActiveProject = useCallback(async () => {
    const pid = Number(activeProject?.id)
    if (!Number.isFinite(pid) || pid <= 0) return
    await runOp(async () => {
      await deleteProject(pid)
      safeStorageRemove(wsKey(pid))
      await queryClient.invalidateQueries({ queryKey: ['projects', selectedOrgId] })
      const remaining = (projectsQuery.data ?? []).filter((p) => p.id !== pid)
      if (remaining.length) {
        selectProjectLocal(remaining[0])
      } else {
        clearActiveProject()
      }
    })
  }, [activeProject?.id, clearActiveProject, projectsQuery.data, queryClient, runOp, selectProjectLocal, selectedOrgId])

  const onScan = useCallback(async () => {
    if (!activeProject) return
    await runOp(async () => {
      const initial = await scanProjectStatus(activeProject.id)
      if (isTaskStatus(initial)) {
        trackTaskStatus(initial, 'scan', `Scan ${activeProject.name}`)
      }
      await waitForTaskResult(initial)
      setGraphStale(false)
      setGraphStaleMessage(null)
      setFileSaveBanner(null)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['graph', selectedOrgId, activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['runs', selectedOrgId, activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['node', selectedOrgId, activeProject.id] }),
      ])
    })
  }, [activeProject, queryClient, runOp, selectedOrgId, trackTaskStatus])

  const onRefresh = useCallback(async () => {
    if (!activeProject) return
    await runOp(async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['graph', selectedOrgId, activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['runs', selectedOrgId, activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['node', selectedOrgId, activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['files', selectedOrgId, activeProject.id] }),
      ])
    })
  }, [activeProject, queryClient, runOp, selectedOrgId])

  const onCreateFile = useCallback(
    async (path: string, content?: string) => {
      if (!activeProject) return
      const p = String(path || '').trim()
      if (!p) return
      let createdPath: string | null = null
      await runOpThrow(async () => {
        const res = await createFile(activeProject.id, p, content)
        const nextPath = String(res?.path || p).trim() || p
        createdPath = nextPath
        queueMutationIndexingPoll(activeProject.id, nextPath, res, 'File created')
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ['files', selectedOrgId, activeProject.id] }),
          queryClient.invalidateQueries({ queryKey: ['graph', selectedOrgId, activeProject.id] }),
          queryClient.invalidateQueries({ queryKey: ['node', selectedOrgId, activeProject.id] }),
        ])
      })
      if (createdPath) {
        setSelection(createdPath, { pushHistory: true })
      }
    },
    [activeProject, queryClient, queueMutationIndexingPoll, runOpThrow, selectedOrgId, setSelection],
  )

  const onRenameFile = useCallback(
    async (path: string, newPath: string) => {
      if (!activeProject) return
      const oldPath = String(path || '').trim()
      const nextRaw = String(newPath || '').trim()
      if (!oldPath || !nextRaw || oldPath === nextRaw) return
      await runOpThrow(async () => {
        const res = await renameFile(activeProject.id, oldPath, nextRaw)
        const nextPath = String(res?.path || nextRaw).trim() || nextRaw
        setOpenFilePaths((prev) => prev.map((item) => (item === oldPath ? nextPath : item)))
        setFileEditorsByPath((prev) => {
          if (!(oldPath in prev)) return prev
          const next = { ...prev }
          const entry = next[oldPath]
          delete next[oldPath]
          next[nextPath] = { ...entry, path: nextPath }
          return next
        })
        setPinnedPaths((prev) => prev.map((item) => (item === oldPath ? nextPath : item)))
        setActiveFilePath((prev) => (prev === oldPath ? nextPath : prev))
        if (selectedPathRef.current === oldPath) {
          setSelection(nextPath, { pushHistory: false })
        }
        queueMutationIndexingPoll(activeProject.id, nextPath, res, 'File renamed')
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ['files', selectedOrgId, activeProject.id] }),
          queryClient.invalidateQueries({ queryKey: ['graph', selectedOrgId, activeProject.id] }),
          queryClient.invalidateQueries({ queryKey: ['node', selectedOrgId, activeProject.id] }),
        ])
      })
    },
    [activeProject, queryClient, queueMutationIndexingPoll, runOpThrow, selectedOrgId, setSelection],
  )

  const onDeleteFile = useCallback(
    async (path: string) => {
      if (!activeProject) return
      const p = String(path || '').trim()
      if (!p) return
      await runOpThrow(async () => {
        const res = await deleteFile(activeProject.id, p)
        setOpenFilePaths((prev) => prev.filter((item) => item !== p))
        setFileEditorsByPath((prev) => {
          if (!(p in prev)) return prev
          const next = { ...prev }
          delete next[p]
          return next
        })
        setPinnedPaths((prev) => prev.filter((item) => item !== p))
        setActiveFilePath((prev) => (prev === p ? null : prev))
        if (selectedPathRef.current === p) {
          setSelection(null, { pushHistory: false })
        }
        queueMutationIndexingPoll(activeProject.id, p, res, 'File deleted')
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ['files', selectedOrgId, activeProject.id] }),
          queryClient.invalidateQueries({ queryKey: ['graph', selectedOrgId, activeProject.id] }),
          queryClient.invalidateQueries({ queryKey: ['node', selectedOrgId, activeProject.id] }),
        ])
      })
    },
    [activeProject, queryClient, queueMutationIndexingPoll, runOpThrow, selectedOrgId, setSelection],
  )

  return {
    onPickProject,
    onCreateProject,
    onDeleteActiveProject,
    onScan,
    onRefresh,
    onCreateFile,
    onRenameFile,
    onDeleteFile,
  }
}
