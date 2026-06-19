import React from 'react'
import type { Project, ProjectFileItem, ProjectTreeEntry } from '@/api'
import { listProjectTreeEntries, searchNodes } from '@/api'
import { safeStorageGet, safeStorageGetJson, safeStorageSet } from '@/shared/lib/storage'

const PAGE_LIMIT = 200

type Params = {
  activeProject: Project | null
  ef: string
  onRegisterFileMeta?: (entries: ProjectTreeEntry[]) => void
}

/**
 * Directory tree data + server search: lazy load/paging of dir entries,
 * open-dirs persistence, and the combined search/initial-load effect.
 * Extracted verbatim from useExplorerTree.
 */
export function useExplorerDirs({ activeProject, ef, onRegisterFileMeta }: Params) {
  type DirState = {
    entries: ProjectTreeEntry[]
    meta: {
      prefix: string
      next_cursor?: string | null
      returned: number
      truncated: boolean
      limit: number
    } | null
    loading: boolean
    error: string | null
  }

  const [dirStates, setDirStates] = React.useState<Record<string, DirState>>({})
  const [searchResults, setSearchResults] = React.useState<ProjectTreeEntry[]>([])
  const [searchBusy, setSearchBusy] = React.useState(false)

  const mergeEntries = React.useCallback((existing: ProjectTreeEntry[], incoming: ProjectTreeEntry[]) => {
    const seen = new Map(existing.map((entry) => [entry.path, entry]))
    const ordered = [...existing]
    for (const entry of incoming) {
      if (seen.has(entry.path)) {
        const idx = ordered.findIndex((item) => item.path === entry.path)
        if (idx >= 0) ordered[idx] = entry
        continue
      }
      seen.set(entry.path, entry)
      ordered.push(entry)
    }
    return ordered
  }, [])

  const loadDir = React.useCallback(
    async (prefix: string, cursor?: string | null) => {
      if (!activeProject) return
      const key = prefix || ''
      setDirStates((prev) => ({
        ...prev,
        [key]: {
          entries: prev[key]?.entries ?? [],
          meta: prev[key]?.meta ?? null,
          loading: true,
          error: null,
        },
      }))
      try {
        const res = await listProjectTreeEntries(activeProject.id, {
          prefix: key || undefined,
          cursor: cursor || undefined,
          limit: PAGE_LIMIT,
        })
        setDirStates((prev) => {
          const existing = prev[key]?.entries ?? []
          const merged = cursor ? mergeEntries(existing, res.entries) : res.entries
          return {
            ...prev,
            [key]: {
              entries: merged,
              meta: res.meta ?? null,
              loading: false,
              error: null,
            },
          }
        })
        onRegisterFileMeta?.(res.entries)
      } catch (error: any) {
        setDirStates((prev) => ({
          ...prev,
          [key]: {
            entries: prev[key]?.entries ?? [],
            meta: prev[key]?.meta ?? null,
            loading: false,
            error: String(error?.message || 'Failed to load directory'),
          },
        }))
      }
    },
    [activeProject, mergeEntries, onRegisterFileMeta],
  )

  React.useEffect(() => {
    if (!activeProject) {
      setDirStates({})
      setSearchResults([])
      return
    }
    setDirStates({})
    setSearchResults([])
    void loadDir('')
  }, [activeProject?.id, loadDir])

  const openDirsStorageKey = React.useMemo(() => {
    const pid = Number(activeProject?.id)
    return Number.isFinite(pid) && pid > 0 ? `cs.ui.explorer.openDirs.v1.${pid}` : null
  }, [activeProject?.id])

  const [openDirs, setOpenDirs] = React.useState<Record<string, boolean>>({})

  React.useEffect(() => {
    if (!openDirsStorageKey) {
      setOpenDirs({})
      return
    }
    const raw = safeStorageGet(openDirsStorageKey)
    if (raw) {
      setOpenDirs((safeStorageGetJson(openDirsStorageKey, {}) as any) || {})
      return
    }
    const legacyRaw = safeStorageGet('cs.ui.explorer.openDirs')
    if (legacyRaw) {
      safeStorageSet(openDirsStorageKey, legacyRaw)
      setOpenDirs((safeStorageGetJson(openDirsStorageKey, {}) as any) || {})
      return
    }
    setOpenDirs({})
  }, [openDirsStorageKey])

  React.useEffect(() => {
    if (!openDirsStorageKey) return
    safeStorageSet(openDirsStorageKey, JSON.stringify(openDirs))
  }, [openDirs, openDirsStorageKey])

  const toggleDir = (path: string) => {
    setOpenDirs((prev) => ({ ...prev, [path]: !prev[path] }))
    const isOpen = openDirs[path] ?? false
    if (!isOpen && !dirStates[path]?.entries?.length && !dirStates[path]?.loading) {
      void loadDir(path)
    }
  }

  React.useEffect(() => {
    if (!activeProject) {
      setSearchResults([])
      setSearchBusy(false)
      return
    }
    if (!ef) {
      setSearchResults([])
      setSearchBusy(false)
      return
    }
    let active = true
    const handle = window.setTimeout(async () => {
      setSearchBusy(true)
      try {
        const results = await searchNodes(activeProject.id, ef, 200)
        if (!active) return
        const entries = (results || [])
          .filter((item) => item?.path)
          .map((item) => ({
            type: 'file' as const,
            path: item.path,
            name: item.path.split('/').pop() || item.path,
            file: {
              path: item.path,
              language: item.language || 'unknown',
              loc: 0,
              complexity: 0,
              fan_in: item.fan_in || 0,
              fan_out: item.fan_out || 0,
              status: 'unknown',
              risk: 0,
            } as ProjectFileItem,
          }))
        setSearchResults(entries)
      } catch {
        if (!active) return
        setSearchResults([])
      } finally {
        if (active) setSearchBusy(false)
      }
    }, 200)
    return () => {
      active = false
      window.clearTimeout(handle)
    }
  }, [activeProject, ef])

  return { dirStates, openDirs, setOpenDirs, loadDir, toggleDir, searchResults, searchBusy }
}
