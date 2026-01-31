// frontend/src/ui/components/ExplorerTree.tsx
import React from 'react'
import type { Project, ProjectFileItem } from '../../api'
import { Modal } from './Modal'

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
  projectFiles: ProjectFileItem[]
  projectFilesMeta: any
  projectFilesBusy: boolean
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
  projectFiles,
  projectFilesMeta,
  projectFilesBusy,
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
    'w-fit max-w-full text-left border rounded-md leading-tight transition-colors disabled:opacity-50',
    compact ? 'text-[10px] px-2 py-1' : 'text-[11px] px-2 py-1.5',
  ].join(' ')
  const itemIdle = 'bg-neutral-950 border-neutral-800 hover:border-neutral-700'
  const itemSelected = 'bg-indigo-950/40 border-indigo-700'
  const itemActive = 'bg-indigo-950/25 border-indigo-600'
  const dirButtonClass = [
    'w-full text-left pr-3 text-xs text-neutral-200 hover:bg-neutral-900',
    compact ? 'py-1.5' : 'py-2',
  ].join(' ')
  const dirChildrenClass = compact ? 'px-2 pb-1 flex flex-col gap-0.5' : 'px-2 pb-1.5 flex flex-col gap-0.5'

  const [explorerFilter, setExplorerFilter] = React.useState('')
  const ef = explorerFilter.trim().toLowerCase()
  const [focusedPath, setFocusedPath] = React.useState<string | null>(null)

  const MAX_DIRS_PER_NODE = 120
  const MAX_FILES_PER_NODE = 160

  const actionsDisabled = busy || projectFilesBusy || !activeProject
  const selectedFilePath = String(selectedPath || '').trim()
  const renameDisabled = actionsDisabled || !selectedFilePath
  const deleteDisabled = actionsDisabled || !selectedFilePath

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

  type DirNode = {
    name: string
    path: string
    dirs: Record<string, DirNode>
    files: ProjectFileItem[]
    fileCount: number
    locSum: number
    fanInSum: number
    fanOutSum: number
    riskMax: number
    riskSum: number
    riskLocSum: number
    riskCount: number
    riskLocDenom: number
  }

  const fmtK = React.useCallback((n: unknown): string => {
    const v = Number(n)
    if (!Number.isFinite(v)) return '—'
    const abs = Math.abs(v)
    if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
    if (abs >= 1_000) return `${Math.round(v / 1_000)}k`
    return String(Math.round(v))
  }, [])

  const toNum = React.useCallback((v: unknown): number => {
    const n = Number(v)
    return Number.isFinite(n) ? n : NaN
  }, [])

  const tree = React.useMemo<DirNode>(() => {
    const root: DirNode = {
      name: '',
      path: '',
      dirs: {},
      files: [],
      fileCount: 0,
      locSum: 0,
      fanInSum: 0,
      fanOutSum: 0,
      riskMax: 0,
      riskSum: 0,
      riskLocSum: 0,
      riskCount: 0,
      riskLocDenom: 0,
    }
    for (const f of projectFiles || []) {
      const p = String(f.path || '').trim()
      if (!p) continue
      const parts = p.split('/').filter(Boolean)
      let cur = root
      for (let i = 0; i < parts.length - 1; i++) {
        const seg = parts[i]
        const nextPath = cur.path ? `${cur.path}/${seg}` : seg
        cur.dirs[seg] =
          cur.dirs[seg] ||
          ({
            name: seg,
            path: nextPath,
            dirs: {},
            files: [],
            fileCount: 0,
            locSum: 0,
            fanInSum: 0,
            fanOutSum: 0,
            riskMax: 0,
            riskSum: 0,
            riskLocSum: 0,
            riskCount: 0,
            riskLocDenom: 0,
          } as DirNode)
        cur = cur.dirs[seg]
      }
      cur.files.push(f)
    }

    const walk = (n: DirNode) => {
      let count = n.files.length
      let locSum = 0
      let fanInSum = 0
      let fanOutSum = 0
      let riskMax = 0
      let riskSum = 0
      let riskLocSum = 0
      let riskCount = 0
      let riskLocDenom = 0

      for (const f of n.files) {
        const loc = toNum((f as any)?.loc)
        const fi = toNum((f as any)?.fan_in)
        const fo = toNum((f as any)?.fan_out)
        const r = toNum((f as any)?.risk)

        if (Number.isFinite(loc) && loc > 0) locSum += loc
        if (Number.isFinite(fi) && fi > 0) fanInSum += fi
        if (Number.isFinite(fo) && fo > 0) fanOutSum += fo
        if (Number.isFinite(r)) {
          riskMax = Math.max(riskMax, r)
          riskSum += r
          riskCount += 1
          if (Number.isFinite(loc) && loc > 0) {
            riskLocSum += r * loc
            riskLocDenom += loc
          }
        }
      }

      const dirKeys = Object.keys(n.dirs).sort()
      for (const k of dirKeys) {
        const c = n.dirs[k]
        walk(c)
        count += c.fileCount
        locSum += c.locSum
        fanInSum += c.fanInSum
        fanOutSum += c.fanOutSum
        riskMax = Math.max(riskMax, c.riskMax)
        riskSum += c.riskSum
        riskLocSum += c.riskLocSum
        riskCount += c.riskCount
        riskLocDenom += c.riskLocDenom
      }
      n.fileCount = count
      n.locSum = locSum
      n.fanInSum = fanInSum
      n.fanOutSum = fanOutSum
      n.riskMax = riskMax
      n.riskSum = riskSum
      n.riskLocSum = riskLocSum
      n.riskCount = riskCount
      n.riskLocDenom = riskLocDenom
    }
    walk(root)
    return root
  }, [projectFiles, toNum])

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
    try {
      const raw = localStorage.getItem(openDirsStorageKey)
      if (raw) {
        setOpenDirs((JSON.parse(raw) as any) || {})
        return
      }
      const legacyRaw = localStorage.getItem('cs.ui.explorer.openDirs')
      if (legacyRaw) {
        localStorage.setItem(openDirsStorageKey, legacyRaw)
        setOpenDirs((JSON.parse(legacyRaw) as any) || {})
        return
      }
    } catch {
      // ignore
    }
    setOpenDirs({})
  }, [openDirsStorageKey])

  React.useEffect(() => {
    if (!openDirsStorageKey) return
    try {
      localStorage.setItem(openDirsStorageKey, JSON.stringify(openDirs))
    } catch {}
  }, [openDirs, openDirsStorageKey])

  const toggleDir = (path: string) => {
    setOpenDirs((prev) => ({ ...prev, [path]: !prev[path] }))
  }

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
    type: 'dir' | 'file'
    isOpen: boolean
    parentPath: string | null
    depth: number
  }

  const visibleEntries = React.useMemo<VisibleEntry[]>(() => {
    if (ef) {
      return (projectFiles || [])
        .filter((f) => String(f.path).toLowerCase().includes(ef))
        .slice(0, 200)
        .map((f) => ({
          path: f.path,
          type: 'file' as const,
          isOpen: false,
          parentPath: f.path.includes('/') ? f.path.split('/').slice(0, -1).join('/') : null,
          depth: 0,
        }))
    }

    const entries: VisibleEntry[] = []
    const rootFiles = (tree.files || [])
      .slice()
      .sort((a, b) => a.path.localeCompare(b.path))
      .slice(0, 120)

    for (const f of rootFiles) {
      entries.push({
        path: f.path,
        type: 'file',
        isOpen: false,
        parentPath: null,
        depth: 0,
      })
    }

    const visitDir = (d: DirNode, depth: number, parentPath: string | null) => {
      const openDefault = depth === 0
      const isOpen = (openDirs[d.path] ?? openDefault) === true
      entries.push({
        path: d.path,
        type: 'dir',
        isOpen,
        parentPath,
        depth,
      })

      if (!isOpen) return
      const dirKeys = Object.keys(d.dirs).sort()
      const shownDirKeys = dirKeys.slice(0, MAX_DIRS_PER_NODE)
      const filesSorted = (d.files || []).slice().sort((a, b) => String(a.path).localeCompare(String(b.path)))
      const shownFiles = filesSorted.slice(0, MAX_FILES_PER_NODE)

      for (const k of shownDirKeys) {
        visitDir(d.dirs[k], depth + 1, d.path)
      }

      for (const f of shownFiles) {
        entries.push({
          path: f.path,
          type: 'file',
          isOpen: false,
          parentPath: d.path,
          depth: depth + 1,
        })
      }
    }

    for (const k of Object.keys(tree.dirs).sort()) {
      visitDir(tree.dirs[k], 0, null)
    }

    return entries
  }, [ef, openDirs, projectFiles, tree])

  const visibleEntryMap = React.useMemo(() => {
    const map = new Map<string, VisibleEntry>()
    for (const entry of visibleEntries) {
      map.set(entry.path, entry)
    }
    return map
  }, [visibleEntries])

  const resolveVisibleFocus = React.useCallback(
    (candidate: string | null) => {
      if (!visibleEntries.length) return null
      if (candidate && visibleEntryMap.has(candidate)) return candidate
      if (selectedPath && visibleEntryMap.has(selectedPath)) return selectedPath
      if (candidate) {
        let cursor = candidate
        while (cursor.includes('/')) {
          cursor = cursor.split('/').slice(0, -1).join('/')
          if (visibleEntryMap.has(cursor)) return cursor
        }
      }
      return visibleEntries[0]?.path ?? null
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
    if (projectFilesBusy) return
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
  }, [ef, projectFilesBusy, selectedPath])

  React.useEffect(() => {
    if (projectFilesBusy) return
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
  }, [ef, ensureVisibleInContainer, projectFilesBusy, selectedPath])

  const isSelectedFile = React.useCallback(
    (path: string) => {
      const p = String(path || '').trim()
      const sel = String(selectedPath || '').trim()
      return !!p && !!sel && p === sel
    },
    [selectedPath],
  )

  const [jumpModule, setJumpModule] = React.useState<string>(() => {
    try {
      const v = (localStorage.getItem('cs.ui.explorer.jumpModule') || '').trim()
      return v || '.'
    } catch {
      return '.'
    }
  })
  const [jumpFile, setJumpFile] = React.useState<string>('')
  React.useEffect(() => {
    try { localStorage.setItem('cs.ui.explorer.jumpModule', jumpModule) } catch {}
  }, [jumpModule])

  const modules = React.useMemo(() => {
    const out: Array<{ key: string; label: string; files: number; loc: number; riskWAvg: number; riskMax: number }> = []
    const rootRiskMax = tree.riskMax
    const rootRiskAvg = tree.riskCount > 0 ? tree.riskSum / tree.riskCount : 0
    const rootRiskWAvg = tree.riskLocDenom > 0 ? tree.riskLocSum / tree.riskLocDenom : rootRiskAvg
    out.push({ key: '.', label: '. (root)', files: tree.fileCount, loc: tree.locSum, riskWAvg: rootRiskWAvg, riskMax: rootRiskMax })
    for (const k of Object.keys(tree.dirs).sort()) {
      const d = tree.dirs[k]
      const riskAvg = d.riskCount > 0 ? d.riskSum / d.riskCount : 0
      const riskWAvg = d.riskLocDenom > 0 ? d.riskLocSum / d.riskLocDenom : riskAvg
      out.push({ key: d.path, label: d.name, files: d.fileCount, loc: d.locSum, riskWAvg, riskMax: d.riskMax })
    }
    return out
  }, [tree])

  const jumpFiles = React.useMemo(() => {
    const key = String(jumpModule || '.')
    const all = projectFiles || []
    const filtered =
      key === '.'
        ? all.filter((f) => !String(f.path || '').includes('/'))
        : all.filter((f) => String(f.path || '').startsWith(`${key}/`))
    return filtered
      .slice()
      .sort((a, b) => String(a.path || '').localeCompare(String(b.path || '')))
  }, [jumpModule, projectFiles])

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
  }, [activeProject, dirDomId, ensureVisibleInContainer, jumpModule, showModuleSelect])

  const renderFile = (f: ProjectFileItem, depth: number, opts?: { showPath?: boolean }) => {
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

  const renderDir = (d: DirNode, depth: number) => {
    const openDefault = depth === 0
    const isOpen = (openDirs[d.path] ?? openDefault) === true
    const focused = focusedPath === d.path
    const pad = 10 + depth * 10

    const riskAvg = d.riskCount > 0 ? d.riskSum / d.riskCount : 0
    const riskWAvg = d.riskLocDenom > 0 ? d.riskLocSum / d.riskLocDenom : riskAvg

    const dirKeys = Object.keys(d.dirs).sort()
    const shownDirKeys = dirKeys.slice(0, MAX_DIRS_PER_NODE)
    const filesSorted = (d.files || []).slice().sort((a, b) => String(a.path).localeCompare(String(b.path)))
    const shownFiles = filesSorted.slice(0, MAX_FILES_PER_NODE)

    const dirTooltip = [
      d.path || '(root)',
      `files: ${d.fileCount}`,
      `loc sum: ${fmtK(d.locSum)}`,
      `fan_in sum: ${fmtK(d.fanInSum)} · fan_out sum: ${fmtK(d.fanOutSum)}`,
      `risk max: ${Number.isFinite(d.riskMax) ? d.riskMax.toFixed(2) : '—'}`,
      `risk avg: ${d.riskCount > 0 && Number.isFinite(riskAvg) ? riskAvg.toFixed(2) : '—'}`,
      `risk weighted(avg, loc): ${d.riskLocDenom > 0 && Number.isFinite(riskWAvg) ? riskWAvg.toFixed(2) : '—'}`,
    ].join('\n')

    return (
      <div key={d.path} id={dirDomId(d.path)} className="border border-neutral-800 rounded-md bg-neutral-950">
        <button
          type="button"
          className={[
            dirButtonClass,
            focused ? 'ring-1 ring-indigo-400' : '',
          ].join(' ')}
          onClick={() => {
            setFocusedPath(d.path)
            toggleDir(d.path)
          }}
          title={dirTooltip}
          style={{ paddingLeft: pad }}
          onMouseDown={(e) => e.preventDefault()}
          onFocus={() => setFocusedPath(d.path)}
          data-explorer-path={d.path}
          role="treeitem"
          aria-expanded={isOpen}
          aria-level={depth + 1}
          tabIndex={focused ? 0 : -1}
        >
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0 flex items-center gap-2">
              <span className="font-semibold text-neutral-200 truncate">
                {isOpen ? '▾' : '▸'} {d.name}
              </span>
              <span className="text-neutral-500 font-normal">({d.fileCount})</span>
            </div>
            <div className="shrink-0 text-[11px] text-neutral-500 font-normal whitespace-nowrap">
              LOC {fmtK(d.locSum)} · RISK {Number.isFinite(riskWAvg) ? riskWAvg.toFixed(2) : '—'}
            </div>
          </div>
        </button>

        {isOpen && (
          <div className={dirChildrenClass} role="group">
            {shownDirKeys.map((k) => renderDir(d.dirs[k], depth + 1))}
            {dirKeys.length > shownDirKeys.length && (
              <div className="text-[11px] text-neutral-500" style={{ marginLeft: (depth + 1) * 10 }}>
                … {dirKeys.length - shownDirKeys.length} More Dirs
              </div>
            )}

            {shownFiles.map((f) => renderFile(f, depth + 1))}

            {filesSorted.length > shownFiles.length && (
              <div className="text-[11px] text-neutral-500" style={{ marginLeft: (depth + 1) * 10 }}>
                … {filesSorted.length - shownFiles.length} More Files
              </div>
            )}
          </div>
        )}
      </div>
    )
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
      const currentIndex = visibleEntries.findIndex((entry) => entry.path === focusedPath)
      if (currentIndex < 0) return
      const current = visibleEntries[currentIndex]

      if (event.key === 'ArrowDown') {
        event.preventDefault()
        const next = visibleEntries[currentIndex + 1]
        if (next) {
          focusEntry(next.path, { scroll: true })
        }
        return
      }

      if (event.key === 'ArrowUp') {
        event.preventDefault()
        const prev = visibleEntries[currentIndex - 1]
        if (prev) {
          focusEntry(prev.path, { scroll: true })
        }
        return
      }

      if (event.key === 'ArrowRight' && current.type === 'dir') {
        event.preventDefault()
        if (!current.isOpen) {
          setOpenDirs((prev) => ({ ...prev, [current.path]: true }))
          return
        }
        const next = visibleEntries[currentIndex + 1]
        if (next && next.parentPath === current.path) {
          focusEntry(next.path, { scroll: true })
        }
        return
      }

      if (event.key === 'ArrowLeft' && current.type === 'dir') {
        event.preventDefault()
        if (current.isOpen) {
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
    [focusEntry, focusedPath, onOpenFileEditor, onSelectPath, visibleEntries],
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
              disabled={!activeProject || busy || projectFilesBusy}
              title="Quick jump to a top-level folder (module). The list shows aggregated metrics."
            >
              {modules.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label} · Files:{m.files} · LOC:{fmtK(m.loc)} · Risk:{Number(m.riskWAvg ?? 0).toFixed(2)}
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
              disabled={!activeProject || busy || projectFilesBusy}
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
        title="Local filter for the file tree (path substring). Does not query the backend."
      />

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
            <div className="text-[11px] font-semibold text-neutral-300">Open Editors ({openEntries.length})</div>
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
          <div className="text-[11px] font-semibold text-neutral-300">Pinned ({pinnedEntries.length})</div>
          <div className="flex flex-col gap-1">
            {pinnedEntries.length > 0 ? (
              pinnedEntries.map((path) => renderQuickEntry(path))
            ) : (
              <div className="text-[11px] text-neutral-500">No pinned files.</div>
            )}
          </div>
        </div>
      </div>

      {projectFilesBusy ? (
        <div className="rounded-md border border-neutral-800 bg-neutral-950 px-3 py-2 text-xs text-neutral-400">
          Loading files…
        </div>
      ) : !activeProject ? (
        <div className="text-xs text-neutral-500">Pick a project.</div>
      ) : (projectFiles?.length || 0) === 0 ? (
        <div className="text-xs text-neutral-500">No files yet (run Scan first).</div>
      ) : (
        <div
          ref={explorerScrollRef}
          className="mt-2 max-h-[55vh] overflow-auto flex flex-col gap-0.5"
          role="tree"
          aria-label="Project files"
          onKeyDown={handleTreeKeyDown}
        >
          {projectFilesMeta?.truncated && (
            <div className="text-[11px] text-amber-300">
              Explorer truncated: shown {projectFilesMeta.returned} of {projectFilesMeta.total}
            </div>
          )}

          {ef ? (
            projectFiles
              .filter((f) => String(f.path).toLowerCase().includes(ef))
              .slice(0, 200)
              .map((f) =>
                renderFile(f, 0, { showPath: true })
              )
          ) : (
            <>
              {(tree.files || [])
                .slice()
                .sort((a, b) => a.path.localeCompare(b.path))
                .slice(0, 120)
                .map((f) => renderFile(f, 0))}

              {Object.keys(tree.dirs)
                .sort()
                .map((k) => renderDir(tree.dirs[k], 0))}
            </>
          )}
        </div>
      )}
    </div>
  )
}
