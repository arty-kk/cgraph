import React from 'react'
import type { Project, ProjectFileItem, ProjectTreeEntry } from '@/api'
import { listProjectTreeEntries, searchNodes } from '@/api'
import { useExplorerDirs } from './useExplorerDirs'
import { safeStorageGet, safeStorageSet } from '@/shared/lib/storage'

export type VisibleEntry = {
  path: string
  type: 'dir' | 'file' | 'loading' | 'load-more' | 'error'
  parentPath: string | null
  depth: number
  entry?: ProjectTreeEntry
  cursor?: string | null
  message?: string
}

type Params = {
  activeProject: Project | null
  selectedPath: string | null
  openFilePaths: string[]
  pinnedPaths: string[]
  showModuleSelect?: boolean
  onSelectPath: (path: string) => void | Promise<void>
  onOpenFileEditor?: (path: string) => void | Promise<void>
  onRegisterFileMeta?: (entries: ProjectTreeEntry[]) => void
}

/**
 * All non-presentational logic for ExplorerTree: directory loading/paging,
 * open-dirs persistence, server search, module/jump derivation, the flattened
 * windowed visible-entry list, keyboard navigation and focus/scroll
 * management. Extracted verbatim from ExplorerTree.
 */
export function useExplorerTree({
  activeProject,
  selectedPath,
  openFilePaths,
  pinnedPaths,
  showModuleSelect,
  onSelectPath,
  onOpenFileEditor,
  onRegisterFileMeta,
}: Params) {
  const explorerScrollRef = React.useRef<HTMLDivElement | null>(null)

  const [explorerFilter, setExplorerFilter] = React.useState('')
  const ef = explorerFilter.trim().toLowerCase()
  const [focusedPath, setFocusedPath] = React.useState<string | null>(null)
  const { dirStates, openDirs, setOpenDirs, loadDir, toggleDir, searchResults, searchBusy } = useExplorerDirs({
    activeProject, ef, onRegisterFileMeta,
  })




  const dirDomId = React.useCallback((p: string) => {
    const s = String(p || '')
    return `cs-explorer-dir-${s.replace(/\//g, '__')}`
  }, [])

  const isFullyVisibleInContainer = React.useCallback((el: HTMLElement, container: HTMLElement) => {
    const er = el.getBoundingClientRect()
    const cr = container.getBoundingClientRect()
    return er.top >= cr.top && er.bottom <= cr.bottom
  }, [])

  const ensureVisibleInContainer = React.useCallback(
    (el: HTMLElement, container: HTMLElement) => {
      if (isFullyVisibleInContainer(el, container)) return
      try {
        el.scrollIntoView({ block: 'nearest' })
      } catch {
        // ignore
      }
    },
    [isFullyVisibleInContainer],
  )

  type VisibleEntry = {
    path: string
    type: 'dir' | 'file' | 'loading' | 'load-more' | 'error'
    parentPath: string | null
    depth: number
    entry?: ProjectTreeEntry
    cursor?: string | null
    message?: string
  }

  const sortedEntries = React.useCallback((entries: ProjectTreeEntry[]) => {
    return entries
      .slice()
      .sort((a, b) => {
        if (a.type !== b.type) return a.type === 'dir' ? -1 : 1
        return a.name.localeCompare(b.name)
      })
  }, [])

  const visibleEntries = React.useMemo<VisibleEntry[]>(() => {
    if (ef) {
      return (searchResults || []).slice(0, 200).map((entry) => ({
        path: entry.path,
        type: 'file' as const,
        parentPath: entry.path.includes('/') ? entry.path.split('/').slice(0, -1).join('/') : null,
        depth: 0,
        entry,
      }))
    }

    const entries: VisibleEntry[] = []
    const visitDir = (dirPath: string, depth: number, parentPath: string | null) => {
      const state = dirStates[dirPath] || { entries: [], loading: false, error: null, meta: null }
      const openDefault = depth === 0
      const isOpen = (openDirs[dirPath] ?? openDefault) === true
      if (dirPath) {
        entries.push({ path: dirPath, type: 'dir', parentPath, depth, entry: { type: 'dir', path: dirPath, name: dirPath.split('/').pop() || dirPath } })
      }

      if (!isOpen && dirPath) return

      const list = sortedEntries(state.entries)
      for (const item of list) {
        if (item.type === 'dir') {
          entries.push({
            path: item.path,
            type: 'dir',
            parentPath: dirPath || null,
            depth: dirPath ? depth + 1 : depth,
            entry: item,
          })
          if ((openDirs[item.path] ?? false) === true) {
            visitDir(item.path, dirPath ? depth + 1 : depth, dirPath || null)
          }
        } else {
          entries.push({
            path: item.path,
            type: 'file',
            parentPath: dirPath || null,
            depth: dirPath ? depth + 1 : depth,
            entry: item,
          })
        }
      }

      if (state.loading) {
        entries.push({
          path: `${dirPath}__loading`,
          type: 'loading',
          parentPath: dirPath || null,
          depth: dirPath ? depth + 1 : depth,
          message: 'Loading…',
        })
      }
      if (state.error) {
        entries.push({
          path: `${dirPath}__error`,
          type: 'error',
          parentPath: dirPath || null,
          depth: dirPath ? depth + 1 : depth,
          message: state.error,
        })
      }
      if (state.meta?.next_cursor) {
        entries.push({
          path: `${dirPath}__more`,
          type: 'load-more',
          parentPath: dirPath || null,
          depth: dirPath ? depth + 1 : depth,
          cursor: state.meta.next_cursor,
          message: 'Load more',
        })
      }
    }

    visitDir('', 0, null)
    return entries
  }, [dirStates, ef, openDirs, searchResults, sortedEntries])

  const visibleEntryMap = React.useMemo(() => {
    const map = new Map<string, VisibleEntry>()
    for (const entry of visibleEntries) {
      if (entry.type === 'dir' || entry.type === 'file') {
        map.set(entry.path, entry)
      }
    }
    return map
  }, [visibleEntries])

  const resolveVisibleFocus = React.useCallback(
    (candidate: string | null) => {
      const navigable = visibleEntries.filter((entry) => entry.type === 'file' || entry.type === 'dir')
      if (!navigable.length) return null
      if (candidate && visibleEntryMap.has(candidate)) return candidate
      if (selectedPath && visibleEntryMap.has(selectedPath)) return selectedPath
      if (candidate) {
        let cursor = candidate
        while (cursor.includes('/')) {
          cursor = cursor.split('/').slice(0, -1).join('/')
          if (visibleEntryMap.has(cursor)) return cursor
        }
      }
      return navigable[0]?.path ?? null
    },
    [selectedPath, visibleEntries, visibleEntryMap],
  )

  React.useEffect(() => {
    setFocusedPath((prev) => {
      const next = resolveVisibleFocus(prev)
      return next === prev ? prev : next
    })
  }, [resolveVisibleFocus])

  const getEntryElement = React.useCallback((path: string) => {
    try {
      return document.querySelector(`[data-explorer-path="${CSS.escape(path)}"]`) as HTMLElement | null
    } catch {
      return document.querySelector(`[data-explorer-path="${path.replace(/"/g, '\\"')}"]`) as HTMLElement | null
    }
  }, [])

  const focusEntry = React.useCallback(
    (path: string, opts?: { scroll?: boolean }) => {
      setFocusedPath(path)
      window.requestAnimationFrame(() => {
        const container = explorerScrollRef.current
        const el = getEntryElement(path)
        if (!el) return
        if (opts?.scroll && container) {
          ensureVisibleInContainer(el, container)
        }
        el.focus()
      })
    },
    [ensureVisibleInContainer, getEntryElement],
  )

  React.useEffect(() => {
    if (ef) return
    const p = String(selectedPath || '').trim()
    if (!p) return
    const parts = p.split('/').filter(Boolean)
    if (parts.length <= 1) return

    setOpenDirs((prev) => {
      let changed = false
      const next = { ...prev }
      let cur = ''
      for (let i = 0; i < parts.length - 1; i++) {
        cur = cur ? `${cur}/${parts[i]}` : parts[i]
        if (next[cur] !== true) {
          next[cur] = true
          changed = true
        }
      }
      return changed ? next : prev
    })
    let current = ''
    for (let i = 0; i < parts.length - 1; i++) {
      current = current ? `${current}/${parts[i]}` : parts[i]
      if (!dirStates[current]?.entries?.length && !dirStates[current]?.loading) {
        void loadDir(current)
      }
    }
  }, [dirStates, ef, loadDir, selectedPath])

  React.useEffect(() => {
    if (ef) return
    const p = String(selectedPath || '').trim()
    if (!p) return
    const t = window.setTimeout(() => {
      const container = explorerScrollRef.current
      const el = document.getElementById('cs-explorer-selected') as HTMLElement | null
      if (!container || !el) return
      ensureVisibleInContainer(el, container)
    }, 0)
    return () => window.clearTimeout(t)
  }, [ef, ensureVisibleInContainer, selectedPath])

  const isSelectedFile = React.useCallback(
    (path: string) => {
      const p = String(path || '').trim()
      const sel = String(selectedPath || '').trim()
      return !!p && !!sel && p === sel
    },
    [selectedPath],
  )

  const toNum = React.useCallback((value: unknown): number => {
    const n = Number(value)
    return Number.isFinite(n) ? n : NaN
  }, [])

  const [jumpModule, setJumpModule] = React.useState<string>(() => {
    const v = (safeStorageGet('cs.ui.explorer.jumpModule', '') || '').trim()
    return v || '.'
  })
  const [jumpFile, setJumpFile] = React.useState<string>('')
  React.useEffect(() => {
    safeStorageSet('cs.ui.explorer.jumpModule', jumpModule)
  }, [jumpModule])

  const modules = React.useMemo(() => {
    const rootEntries = dirStates['']?.entries ?? []
    const out: Array<{ key: string; label: string; files: number }> = []
    const rootFiles = rootEntries.filter((entry) => entry.type === 'file').length
    out.push({ key: '.', label: '. (root)', files: rootFiles })
    rootEntries
      .filter((entry) => entry.type === 'dir')
      .sort((a, b) => a.name.localeCompare(b.name))
      .forEach((entry) => {
        const count = dirStates[entry.path]?.entries?.length ?? 0
        out.push({ key: entry.path, label: entry.name, files: count })
      })
    return out
  }, [dirStates])

  const jumpFiles = React.useMemo(() => {
    const key = String(jumpModule || '.')
    const stateKey = key === '.' ? '' : key
    const entries = dirStates[stateKey]?.entries ?? []
    const files = entries.filter((entry) => entry.type === 'file')
    return files
      .map((entry) => entry.file ?? { path: entry.path } as ProjectFileItem)
      .sort((a, b) => String(a.path || '').localeCompare(String(b.path || '')))
  }, [dirStates, jumpModule])

  const openEntries = React.useMemo(
    () => (openFilePaths || []).map((p) => String(p || '').trim()).filter(Boolean),
    [openFilePaths],
  )
  const pinnedEntries = React.useMemo(
    () => (pinnedPaths || []).map((p) => String(p || '').trim()).filter(Boolean),
    [pinnedPaths],
  )

  React.useEffect(() => {
    if (!showModuleSelect) return
    if (!activeProject) return
    const key = String(jumpModule || '.')
    if (!key || key === '.') return
    if (!dirStates[key]?.entries?.length && !dirStates[key]?.loading) {
      void loadDir(key)
    }
    setOpenDirs((prev) => {
      if (prev[key] === true) return prev
      return { ...prev, [key]: true }
    })
    const t = window.setTimeout(() => {
      const el = document.getElementById(dirDomId(key))
      const container = explorerScrollRef.current
      if (!container || !el) return
      ensureVisibleInContainer(el as HTMLElement, container)
    }, 0)
    return () => window.clearTimeout(t)
  }, [activeProject, dirDomId, dirStates, ensureVisibleInContainer, jumpModule, loadDir, showModuleSelect])


  const handleTreeKeyDown = React.useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (!visibleEntries.length) return
      if (!focusedPath) return
      const navigable = visibleEntries.filter((entry) => entry.type === 'file' || entry.type === 'dir')
      const currentIndex = navigable.findIndex((entry) => entry.path === focusedPath)
      if (currentIndex < 0) return
      const current = navigable[currentIndex]

      if (event.key === 'ArrowDown') {
        event.preventDefault()
        const next = navigable[currentIndex + 1]
        if (next) {
          focusEntry(next.path, { scroll: true })
        }
        return
      }

      if (event.key === 'ArrowUp') {
        event.preventDefault()
        const prev = navigable[currentIndex - 1]
        if (prev) {
          focusEntry(prev.path, { scroll: true })
        }
        return
      }

      if (event.key === 'ArrowRight' && current.type === 'dir') {
        event.preventDefault()
        if (!(openDirs[current.path] ?? false)) {
          setOpenDirs((prev) => ({ ...prev, [current.path]: true }))
          if (!dirStates[current.path]?.entries?.length && !dirStates[current.path]?.loading) {
            void loadDir(current.path)
          }
          return
        }
        const next = navigable[currentIndex + 1]
        if (next && next.parentPath === current.path) {
          focusEntry(next.path, { scroll: true })
        }
        return
      }

      if (event.key === 'ArrowLeft' && current.type === 'dir') {
        event.preventDefault()
        if (openDirs[current.path] ?? false) {
          setOpenDirs((prev) => ({ ...prev, [current.path]: false }))
          return
        }
        if (current.parentPath) {
          focusEntry(current.parentPath, { scroll: true })
        }
        return
      }

      if (event.key === 'Enter' && current.type === 'file') {
        event.preventDefault()
        if (onOpenFileEditor) {
          void Promise.resolve(onOpenFileEditor(current.path))
        } else {
          void Promise.resolve(onSelectPath(current.path))
        }
      }
    },
    [dirStates, focusEntry, focusedPath, loadDir, onOpenFileEditor, onSelectPath, openDirs, visibleEntries],
  )

  return {
    explorerScrollRef, explorerFilter, setExplorerFilter, ef, focusedPath, setFocusedPath,
    dirStates, searchResults, searchBusy, openDirs, jumpModule, setJumpModule, jumpFile, setJumpFile,
    modules, jumpFiles, visibleEntries, openEntries, pinnedEntries,
    loadDir, toggleDir, focusEntry, isSelectedFile, toNum, dirDomId, handleTreeKeyDown,
  }
}
