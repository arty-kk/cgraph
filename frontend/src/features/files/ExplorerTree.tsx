// frontend/src/ui/components/ExplorerTree.tsx
import React from 'react'
import type { Project, ProjectFileItem, ProjectTreeEntry } from '@/api'
import { listProjectTreeEntries, searchNodes } from '@/api'
import { Modal } from '@/shared/ui/Modal'
import { safeStorageGet, safeStorageGetJson, safeStorageSet } from '@/shared/lib/storage'

type ExplorerTreeProps = {
  activeProject: Project | null
  busy: boolean
  openFilePaths: string[]
  activeFilePath: string | null
  selectedPath: string | null
  dirtyPath?: string | null
  pinnedPaths: string[]
  onSelectPath: (path: string) => void | Promise<void>
  onCreateFile: (path: string) => void | Promise<void>
  onRenameFile: (path: string, newPath: string) => void | Promise<void>
  onDeleteFile: (path: string) => void | Promise<void>
  onOpenFileEditor?: (path: string) => void | Promise<void>
  onRegisterFileMeta?: (entries: ProjectTreeEntry[]) => void
  showModuleSelect?: boolean
  compact?: boolean
  showOpenEditors?: boolean
}

export function ExplorerTree({
  activeProject,
  busy,
  openFilePaths = [],
  activeFilePath = null,
  selectedPath,
  dirtyPath = null,
  pinnedPaths = [],
  onSelectPath,
  onCreateFile,
  onRenameFile,
  onDeleteFile,
  onOpenFileEditor,
  onRegisterFileMeta,
  showModuleSelect = true,
  compact = false,
  showOpenEditors = true,
}: ExplorerTreeProps) {
  const explorerScrollRef = React.useRef<HTMLDivElement | null>(null)

  const controlBase = 'w-full h-9 rounded-md bg-neutral-900 border border-neutral-800 px-2 text-xs outline-none'
  const controlDisabled = 'disabled:opacity-50'
  const controlClass = `${controlBase} ${controlDisabled}`
  const labelRowClass = 'flex items-center gap-2 leading-none'
  const fieldLabelClass = 'text-[11px] font-semibold text-neutral-200'
  const inputSmClass = 'w-full h-9 rounded-md bg-neutral-900 border border-neutral-800 px-3 text-sm outline-none disabled:opacity-50'

  const itemBase = [
    'w-full max-w-full text-left leading-tight transition-colors disabled:opacity-50',
    compact ? 'text-[11px] px-2 py-1 rounded-sm' : 'text-[11px] px-2 py-1.5 rounded-md border',
  ].join(' ')
  const itemIdle = compact
    ? 'bg-transparent hover:bg-neutral-900/70'
    : 'bg-neutral-950 border-neutral-800 hover:border-neutral-700'
  const itemSelected = compact
    ? 'bg-indigo-500/10'
    : 'bg-indigo-950/40 border-indigo-700'
  const itemActive = compact
    ? 'bg-indigo-500/5'
    : 'bg-indigo-950/25 border-indigo-600'
  const dirButtonClass = [
    'w-full text-left pr-3 text-xs text-neutral-200 hover:bg-neutral-900/70',
    compact ? 'py-1' : 'py-2',
  ].join(' ')
  const sectionHeaderClass = compact
    ? 'text-[10px] uppercase tracking-[0.2em] text-neutral-500'
    : 'text-[11px] font-semibold text-neutral-300'

  const [explorerFilter, setExplorerFilter] = React.useState('')
  const ef = explorerFilter.trim().toLowerCase()
  const [focusedPath, setFocusedPath] = React.useState<string | null>(null)

  const PAGE_LIMIT = 200

  const actionsDisabled = busy || !activeProject
  const selectedFilePath = String(selectedPath || '').trim()
  const renameDisabled = actionsDisabled || !selectedFilePath
  const deleteDisabled = actionsDisabled || !selectedFilePath

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

  const [createOpen, setCreateOpen] = React.useState(false)
  const [renameOpen, setRenameOpen] = React.useState(false)
  const [deleteOpen, setDeleteOpen] = React.useState(false)
  const [createInput, setCreateInput] = React.useState('')
  const [renameInput, setRenameInput] = React.useState('')
  const [createError, setCreateError] = React.useState<string | null>(null)
  const [renameError, setRenameError] = React.useState<string | null>(null)
  const [createOpError, setCreateOpError] = React.useState<string | null>(null)
  const [renameOpError, setRenameOpError] = React.useState<string | null>(null)
  const [deleteOpError, setDeleteOpError] = React.useState<string | null>(null)
  const [openAfterCreate, setOpenAfterCreate] = React.useState(false)
  const [revealInEditor, setRevealInEditor] = React.useState(false)

  const validatePath = React.useCallback((input: string): string | null => {
    const raw = String(input ?? '')
    if (!raw.trim()) return 'Path is required.'
    if (raw !== raw.trim()) return 'Path must not include leading or trailing spaces.'
    if (raw.includes('..')) return 'Path must not contain ".." segments.'
    if (raw.startsWith('/') || /^[A-Za-z]:[\\/]/.test(raw)) return 'Path must be relative to the project root.'
    return null
  }, [])

  React.useEffect(() => {
    if (createOpen) {
      setCreateInput('')
      setCreateError(null)
      setCreateOpError(null)
      return
    }
    setCreateError(null)
    setCreateOpError(null)
  }, [createOpen])

  React.useEffect(() => {
    if (renameOpen) {
      setRenameInput(selectedFilePath)
      setRenameError(null)
      setRenameOpError(null)
      return
    }
    setRenameError(null)
    setRenameOpError(null)
  }, [renameOpen, selectedFilePath])

  React.useEffect(() => {
    if (deleteOpen) {
      setDeleteOpError(null)
      return
    }
    setDeleteOpError(null)
  }, [deleteOpen])

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

  const renderFile = (entry: ProjectTreeEntry, depth: number, opts?: { showPath?: boolean }) => {
    const f: ProjectFileItem = entry.file ?? {
      path: entry.path,
      language: 'unknown',
      loc: 0,
      complexity: 0,
      fan_in: 0,
      fan_out: 0,
      status: 'unknown',
      risk: 0,
    }
    const selected = isSelectedFile(f.path)
    const isActive = Boolean(activeFilePath && activeFilePath === f.path)
    const focused = focusedPath === f.path
    const isDirty = !!dirtyPath && dirtyPath === f.path
    const name = f.path.split('/').pop() || f.path
    const showPath = Boolean(opts?.showPath)
    const canOpenInEditor = Boolean(onOpenFileEditor)
    const isDisabled = !activeProject || busy
    const lang = String((f as any)?.language ?? '—')
    const risk = toNum((f as any)?.risk)
    const loc = toNum((f as any)?.loc)
    const fi = toNum((f as any)?.fan_in)
    const fo = toNum((f as any)?.fan_out)

    const tooltip = [
      f.path,
      ...(canOpenInEditor ? ['Double-click to open'] : []),
      `lang: ${lang}`,
      `risk: ${Number.isFinite(risk) ? risk.toFixed(2) : '—'}`,
      `loc: ${Number.isFinite(loc) ? String(loc) : '—'}`,
      `fan_in/out: ${Number.isFinite(fi) ? String(fi) : '—'}/${Number.isFinite(fo) ? String(fo) : '—'}`,
    ].join('\n')
    return (
      <div
        key={f.path}
        style={{ marginLeft: depth > 0 ? depth * 10 : 0 }}
        className="flex items-center gap-2"
      >
        <button
          id={selected ? 'cs-explorer-selected' : undefined}
          className={[
            itemBase,
            selected ? itemSelected : isActive ? itemActive : itemIdle,
            focused ? 'ring-1 ring-indigo-400' : '',
            isDisabled ? 'cursor-not-allowed' : 'cursor-pointer',
            'flex items-center justify-between gap-2 min-w-0',
          ].join(' ')}
          data-explorer-path={f.path}
          role="treeitem"
          aria-level={depth + 1}
          tabIndex={focused ? 0 : -1}
          onClick={() => {
            if (isDisabled) return
            setFocusedPath(f.path)
            void Promise.resolve(onSelectPath(f.path))
          }}
          onDoubleClick={() => {
            if (isDisabled || !canOpenInEditor) return
            void Promise.resolve(onOpenFileEditor?.(f.path))
          }}
          onFocus={() => setFocusedPath(f.path)}
          onMouseDown={(e) => e.preventDefault()}
          disabled={isDisabled}
          title={tooltip}
        >
          <div className="flex items-center gap-2 text-neutral-200 truncate">
            <span className="truncate">{showPath ? f.path : name}</span>
            {isDirty && (
              <span className="text-amber-300" aria-label="Unsaved changes" title="Unsaved changes">
                ●
              </span>
            )}
          </div>
        </button>
        {canOpenInEditor && showOpenEditors && (
          <button
            type="button"
            className="shrink-0 rounded-md border border-neutral-800 bg-neutral-900 px-1.5 py-0.5 text-[10px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
            title="Open file"
            onMouseDown={(e) => {
              e.preventDefault()
              e.stopPropagation()
            }}
            onClick={(e) => {
              e.preventDefault()
              e.stopPropagation()
              void Promise.resolve(onOpenFileEditor?.(f.path))
            }}
            disabled={isDisabled}
          >
            Open
          </button>
        )}
      </div>
    )
  }

  const renderQuickEntry = (path: string) => {
    const name = path.split('/').pop() || path
    const isActive = Boolean(activeFilePath && activeFilePath === path)
    const isSelected = isSelectedFile(path)
    const isDirty = !!dirtyPath && dirtyPath === path
    const isDisabled = !activeProject || busy
    const handleOpen = () => {
      if (isDisabled) return
      if (onOpenFileEditor) {
        void Promise.resolve(onOpenFileEditor(path))
      } else {
        void Promise.resolve(onSelectPath(path))
      }
    }

    return (
      <button
        key={path}
        type="button"
        className={[
          itemBase,
          isSelected ? itemSelected : isActive ? itemActive : itemIdle,
          isDisabled ? 'cursor-not-allowed' : 'cursor-pointer',
          'w-full flex items-center justify-between gap-2 min-w-0',
        ].join(' ')}
        onClick={handleOpen}
        disabled={isDisabled}
        title={path}
      >
        <span className="truncate text-neutral-200">{name}</span>
        {isDirty && (
          <span className="text-amber-300" aria-label="Unsaved changes" title="Unsaved changes">
            ●
          </span>
        )}
      </button>
    )
  }

  const renderDirEntry = (entry: ProjectTreeEntry, depth: number) => {
    const isOpen = (openDirs[entry.path] ?? false) === true
    const focused = focusedPath === entry.path
    const pad = 10 + depth * 10
    const name = entry.name || entry.path.split('/').pop() || entry.path
    const count = dirStates[entry.path]?.entries?.length ?? 0

    return (
      <div key={entry.path} id={dirDomId(entry.path)} className={compact ? 'flex flex-col' : 'border border-neutral-800 rounded-md bg-neutral-950'}>
        <button
          type="button"
          className={[
            dirButtonClass,
            focused ? 'ring-1 ring-indigo-400' : '',
          ].join(' ')}
          onClick={() => {
            setFocusedPath(entry.path)
            toggleDir(entry.path)
          }}
          style={{ paddingLeft: pad }}
          onMouseDown={(e) => e.preventDefault()}
          onFocus={() => setFocusedPath(entry.path)}
          data-explorer-path={entry.path}
          role="treeitem"
          aria-expanded={isOpen}
          aria-level={depth + 1}
          tabIndex={focused ? 0 : -1}
        >
          <div className="flex items-center gap-2 min-w-0">
            <span className="font-semibold text-neutral-200 truncate">
              {isOpen ? '▾' : '▸'} {name}
            </span>
            <span className="text-neutral-500 font-normal">{count > 0 ? `(${count})` : ''}</span>
          </div>
        </button>
      </div>
    )
  }

  const [scrollTop, setScrollTop] = React.useState(0)
  const [viewportHeight, setViewportHeight] = React.useState(0)
  const rowHeight = compact ? 22 : 28
  const overscan = 6

  React.useEffect(() => {
    const container = explorerScrollRef.current
    if (!container) return
    const update = () => setViewportHeight(container.clientHeight)
    update()
    if (typeof ResizeObserver === 'undefined') return
    const obs = new ResizeObserver(update)
    obs.observe(container)
    return () => obs.disconnect()
  }, [explorerScrollRef])

  const windowed = React.useMemo(() => {
    const total = visibleEntries.length
    if (total === 0) return { items: [], paddingTop: 0, paddingBottom: 0 }
    const startIndex = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan)
    const endIndex = Math.min(
      total,
      Math.ceil((scrollTop + viewportHeight) / rowHeight) + overscan,
    )
    const items = visibleEntries.slice(startIndex, endIndex)
    const paddingTop = startIndex * rowHeight
    const paddingBottom = Math.max(0, (total - endIndex) * rowHeight)
    return { items, paddingTop, paddingBottom }
  }, [overscan, rowHeight, scrollTop, viewportHeight, visibleEntries])

  const renderEntry = (entry: VisibleEntry) => {
    if (entry.type === 'dir') {
      return renderDirEntry(entry.entry as ProjectTreeEntry, entry.depth)
    }
    if (entry.type === 'file') {
      return renderFile(entry.entry as ProjectTreeEntry, entry.depth, { showPath: Boolean(ef) })
    }
    if (entry.type === 'load-more') {
      return (
        <div key={entry.path} style={{ marginLeft: entry.depth * 10 }} className="text-[11px] text-neutral-400">
          <button
            type="button"
            className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[10px] font-semibold text-neutral-200 hover:bg-neutral-800"
            onClick={() => void loadDir(entry.parentPath || '', entry.cursor)}
          >
            {entry.message || 'Load more'}
          </button>
        </div>
      )
    }
    if (entry.type === 'loading') {
      return (
        <div key={entry.path} style={{ marginLeft: entry.depth * 10 }} className="text-[11px] text-neutral-500">
          {entry.message || 'Loading…'}
        </div>
      )
    }
    if (entry.type === 'error') {
      return (
        <div key={entry.path} style={{ marginLeft: entry.depth * 10 }} className="text-[11px] text-rose-300">
          {entry.message || 'Failed to load'}
        </div>
      )
    }
    return null
  }

  const handleCreateSubmit = React.useCallback(async () => {
    if (actionsDisabled) return
    const err = validatePath(createInput)
    setCreateError(err)
    setCreateOpError(null)
    if (err) return
    const nextPath = createInput.trim()
    try {
      await Promise.resolve(onCreateFile(nextPath))
      if (revealInEditor) {
        await Promise.resolve(onSelectPath(nextPath))
      }
      if (openAfterCreate && onOpenFileEditor) {
        await Promise.resolve(onOpenFileEditor(nextPath))
      }
      setCreateOpen(false)
    } catch (e: any) {
      const message = e instanceof Error ? e.message : String(e)
      setCreateOpError(message || 'Failed to create file.')
    }
  }, [actionsDisabled, createInput, onCreateFile, onOpenFileEditor, onSelectPath, openAfterCreate, revealInEditor, validatePath])

  const handleRenameSubmit = React.useCallback(async () => {
    if (renameDisabled) return
    const err = validatePath(renameInput)
    setRenameError(err)
    setRenameOpError(null)
    if (err) return
    const nextPath = renameInput.trim()
    try {
      await Promise.resolve(onRenameFile(selectedFilePath, nextPath))
      if (revealInEditor) {
        await Promise.resolve(onSelectPath(nextPath))
      }
      setRenameOpen(false)
    } catch (e: any) {
      const message = e instanceof Error ? e.message : String(e)
      setRenameOpError(message || 'Failed to rename file.')
    }
  }, [onRenameFile, onSelectPath, renameDisabled, renameInput, revealInEditor, selectedFilePath, validatePath])

  const handleDeleteSubmit = React.useCallback(async () => {
    if (deleteDisabled) return
    setDeleteOpError(null)
    try {
      await Promise.resolve(onDeleteFile(selectedFilePath))
      setDeleteOpen(false)
    } catch (e: any) {
      const message = e instanceof Error ? e.message : String(e)
      setDeleteOpError(message || 'Failed to delete file.')
    }
  }, [deleteDisabled, onDeleteFile, selectedFilePath])

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

  return (
    <div className="flex flex-col gap-2">
      {showModuleSelect && (
        <div className="grid grid-cols-2 gap-2">
          <label className="text-xs text-neutral-300">
            <div className={labelRowClass}>
              <span className={fieldLabelClass}>Module</span>
            </div>
            <select
              className={controlClass + ' mt-1'}
              value={jumpModule}
              onChange={(e) => {
                setJumpModule(e.target.value || '.')
                setJumpFile('')
              }}
              disabled={!activeProject || busy}
              title="Quick jump to a top-level folder (module)."
            >
              {modules.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label} · Files:{m.files}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-neutral-300">
            <div className={labelRowClass}>
              <span className={fieldLabelClass}>File</span>
            </div>
            <select
              className={controlClass + ' mt-1'}
              value={jumpFile}
              onChange={(e) => {
                const p = String(e.target.value || '').trim()
                setJumpFile(p)
                if (p) void Promise.resolve(onSelectPath(p))
              }}
              disabled={!activeProject || busy}
              title="Quick jump to a file inside the selected module"
            >
              <option value="">—</option>
              {jumpFiles.slice(0, 250).map((f) => (
                <option key={f.path} value={f.path}>
                  {f.path}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      <input
        className={inputSmClass}
        placeholder="Filter (Path)…"
        value={explorerFilter}
        onChange={(e) => setExplorerFilter(e.target.value)}
        disabled={!activeProject || busy}
        title="Search files by path (server query)."
      />

      {!compact && (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
            disabled={actionsDisabled}
            onClick={() => {
              if (actionsDisabled) return
              setCreateOpen(true)
            }}
            title="Create new file"
          >
            Create
          </button>
          <button
            type="button"
            className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
            disabled={renameDisabled}
            onClick={() => {
              if (renameDisabled) return
              setRenameOpen(true)
            }}
            title="Rename selected file"
          >
            Rename
          </button>
          <button
            type="button"
            className="rounded-md border border-rose-900/70 bg-rose-950/40 px-2 py-1 text-[11px] font-semibold text-rose-100 hover:bg-rose-900/40 disabled:opacity-50"
            disabled={deleteDisabled}
            onClick={() => {
              if (deleteDisabled) return
              setDeleteOpen(true)
            }}
            title="Delete selected file"
          >
            Delete
          </button>
        </div>
      )}

      <Modal
        open={createOpen}
        title="Create file"
        onClose={() => setCreateOpen(false)}
        panelClassName="w-[min(520px,calc(100vw-32px))]"
      >
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            void handleCreateSubmit()
          }}
        >
          <label className="text-xs text-neutral-300">
            <div className={labelRowClass}>
              <span className={fieldLabelClass}>Path</span>
            </div>
            <input
              className={inputSmClass + ' mt-1'}
              value={createInput}
              onChange={(e) => {
                setCreateInput(e.target.value)
                setCreateError(null)
                setCreateOpError(null)
              }}
              placeholder="relative/path/to/file.ts"
              disabled={actionsDisabled}
              autoFocus
            />
          </label>
          {createError && (
            <div className="text-[11px] text-rose-300">{createError}</div>
          )}
          {createOpError && (
            <div className="text-[11px] text-rose-300">{createOpError}</div>
          )}
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-[11px] text-neutral-300">
              <input
                type="checkbox"
                className="accent-indigo-500"
                checked={openAfterCreate}
                onChange={(e) => setOpenAfterCreate(e.target.checked)}
              />
              Open after create
            </label>
            <label className="flex items-center gap-2 text-[11px] text-neutral-300">
              <input
                type="checkbox"
                className="accent-indigo-500"
                checked={revealInEditor}
                onChange={(e) => setRevealInEditor(e.target.checked)}
              />
              Reveal in editor
            </label>
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800"
              onClick={() => setCreateOpen(false)}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
              disabled={actionsDisabled}
            >
              Create
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        open={renameOpen}
        title="Rename file"
        onClose={() => setRenameOpen(false)}
        panelClassName="w-[min(520px,calc(100vw-32px))]"
      >
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            void handleRenameSubmit()
          }}
        >
          <label className="text-xs text-neutral-300">
            <div className={labelRowClass}>
              <span className={fieldLabelClass}>New path</span>
            </div>
            <input
              className={inputSmClass + ' mt-1'}
              value={renameInput}
              onChange={(e) => {
                setRenameInput(e.target.value)
                setRenameError(null)
                setRenameOpError(null)
              }}
              placeholder={selectedFilePath}
              disabled={renameDisabled}
              autoFocus
            />
          </label>
          {renameError && (
            <div className="text-[11px] text-rose-300">{renameError}</div>
          )}
          {renameOpError && (
            <div className="text-[11px] text-rose-300">{renameOpError}</div>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800"
              onClick={() => setRenameOpen(false)}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
              disabled={renameDisabled}
            >
              Rename
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        open={deleteOpen}
        title="Delete file"
        onClose={() => setDeleteOpen(false)}
        panelClassName="w-[min(520px,calc(100vw-32px))]"
      >
        <div className="space-y-3">
          <div className="text-sm text-neutral-200">
            Delete file "{selectedFilePath}"? This action cannot be undone.
          </div>
          {deleteOpError && (
            <div className="text-[11px] text-rose-300">{deleteOpError}</div>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800"
              onClick={() => setDeleteOpen(false)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="rounded-md border border-rose-900/70 bg-rose-950/40 px-3 py-1 text-[11px] font-semibold text-rose-100 hover:bg-rose-900/40 disabled:opacity-50"
              onClick={() => void handleDeleteSubmit()}
              disabled={deleteDisabled}
            >
              Yes
            </button>
          </div>
        </div>
      </Modal>

      <div className="space-y-2">
        {showOpenEditors && (
          <div className="space-y-1">
            <div className={sectionHeaderClass}>Open Editors ({openEntries.length})</div>
            <div className="flex flex-col gap-1">
              {openEntries.length > 0 ? (
                openEntries.map((path) => renderQuickEntry(path))
              ) : (
                <div className="text-[11px] text-neutral-500">No open editors.</div>
              )}
            </div>
          </div>
        )}
        <div className="space-y-1">
          <div className={sectionHeaderClass}>Pinned ({pinnedEntries.length})</div>
          <div className="flex flex-col gap-1">
            {pinnedEntries.length > 0 ? (
              pinnedEntries.map((path) => renderQuickEntry(path))
            ) : (
              <div className="text-[11px] text-neutral-500">No pinned files.</div>
            )}
          </div>
        </div>
      </div>

      {!activeProject ? (
        <div className="text-xs text-neutral-500">Pick a project.</div>
      ) : (
        <div
          ref={explorerScrollRef}
          className={[
            'mt-2 overflow-auto flex flex-col gap-0.5',
            compact ? 'min-h-0' : 'max-h-[55vh]',
          ].join(' ')}
          role="tree"
          aria-label="Project files"
          onKeyDown={handleTreeKeyDown}
          onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}
        >
          {searchBusy && ef && (
            <div className="text-[11px] text-neutral-500">Searching…</div>
          )}
          {!searchBusy && ef && searchResults.length === 0 && (
            <div className="text-[11px] text-neutral-500">No matches.</div>
          )}
          {!ef && dirStates['']?.loading && visibleEntries.length === 0 && (
            <div className="rounded-md border border-neutral-800 bg-neutral-950 px-3 py-2 text-xs text-neutral-400">
              Loading files…
            </div>
          )}
          {!ef && !dirStates['']?.loading && visibleEntries.length === 0 && (
            <div className="text-xs text-neutral-500">No files yet (run Scan first).</div>
          )}
          {visibleEntries.length > 0 && (
            <div style={{ paddingTop: windowed.paddingTop, paddingBottom: windowed.paddingBottom }}>
              {windowed.items.map((entry) => renderEntry(entry))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
