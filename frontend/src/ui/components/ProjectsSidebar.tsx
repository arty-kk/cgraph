// frontend/src/ui/components/ProjectsSidebar.tsx
import React from 'react'
import type { Project, ProjectFileItem, NodeSearchItem, SemanticSearchItem } from '../../api'
import { clampInt } from '../../lib/number'
import type { SemanticSearchErrorReason } from '../../lib/errors'
import { Modal } from './Modal'

type Props = {
  onHidePanel?: () => void
  projects: Project[]
  activeProject: Project | null
  selectedPath: string | null
  projectsLoading: boolean
  newName: string
  newPath: string
  busy: boolean
  error: string | null

  setNewName: (v: string) => void
  setNewPath: (v: string) => void

  onDeleteActiveProject: () => void | Promise<void>
  
  // graph controls
  graphMode: 'local' | 'full' | 'limit'
  graphLimitN: number
  graphHops: number
  graphLocalMax: number
  setGraphMode: (v: 'local' | 'full' | 'limit') => void
  setGraphLimitN: (v: number) => void
  setGraphHops: (v: number) => void
  setGraphLocalMax: (v: number) => void

  searchQuery: string
  searchResults: NodeSearchItem[]
  searchSemanticResults: SemanticSearchItem[]
  semanticSearchFallbackUsed: boolean
  semanticSearchEnabled: boolean
  semanticSearchUnavailableReason: SemanticSearchErrorReason | null
  searchBusy: boolean
  setSearchQuery: (v: string) => void
  setSemanticSearchEnabled: (v: boolean) => void
  onSearchNodes: (q: string) => void | Promise<void>

  onPickProject: (p: Project) => void | Promise<void>
  onCreateProject: () => void | Promise<void>
  onScan: () => void | Promise<void>
  onRefresh: () => void | Promise<void>
  onSelectPath: (path: string) => void | Promise<void>

  projectFiles: ProjectFileItem[]
  projectFilesMeta: any
  projectFilesBusy: boolean

  onOpenDocs: () => void | Promise<void>
}

export function ProjectsSidebar({
  onHidePanel,
  projects,
  activeProject,
  selectedPath,
  projectsLoading,
  newName,
  newPath,
  busy,
  error,
  setNewName,
  setNewPath,
  onDeleteActiveProject,
  graphMode,
  graphLimitN,
  graphHops,
  graphLocalMax,
  setGraphMode,
  setGraphLimitN,
  setGraphHops,
  setGraphLocalMax,
  searchQuery,
  searchResults,
  searchSemanticResults,
  semanticSearchFallbackUsed,
  semanticSearchEnabled,
  semanticSearchUnavailableReason,
  searchBusy,
  setSearchQuery,
  setSemanticSearchEnabled,
  onSearchNodes,
  onPickProject,
  onCreateProject,
  onScan,
  onRefresh,
  onSelectPath,
  projectFiles,
  projectFilesMeta,
  projectFilesBusy,
  onOpenDocs,
}: Props) {
  const [helpOpen, setHelpOpen] = React.useState<null | 'projects' | 'graph' | 'search'>(null)
  const [confirmDeleteOpen, setConfirmDeleteOpen] = React.useState(false)

  const explorerScrollRef = React.useRef<HTMLDivElement | null>(null)

  const controlBase = 'w-full h-9 rounded-md bg-neutral-900 border border-neutral-800 px-2 text-xs outline-none'
  const controlDisabled = 'disabled:opacity-50'
  const controlClass = `${controlBase} ${controlDisabled}`
  const labelRowClass = 'flex items-center gap-2 leading-none'
  const fieldLabelClass = 'text-[11px] font-semibold text-neutral-200'

  const controlSmBase = 'h-9 rounded-md bg-neutral-900 border border-neutral-800 text-sm outline-none disabled:opacity-50'
  const inputSmClass = `w-full ${controlSmBase} px-3`
  const inputSmFlexClass = `flex-1 ${controlSmBase} px-3`
  const selectSmFlexClass = `min-w-0 flex-1 ${controlSmBase} px-2`

  const buttonBase = 'h-9 rounded-md border border-neutral-800 px-3 text-sm font-semibold disabled:opacity-50'
  const buttonNeutral = `${buttonBase} bg-neutral-900 hover:bg-neutral-800`
  const buttonSoft = `${buttonBase} bg-neutral-800 hover:bg-neutral-700 border-neutral-800`
  const buttonDanger = 'h-9 rounded-md bg-neutral-900 hover:bg-red-950 border border-neutral-800 hover:border-red-800 px-3 text-sm font-semibold disabled:opacity-50'
  const buttonPrimary = 'h-9 rounded-md bg-indigo-600 hover:bg-indigo-500 px-3 text-sm font-semibold disabled:opacity-50'
  const miniButtonClass = 'h-6 rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2.5 text-[11px] font-semibold disabled:opacity-50'
  
  const tabBase = 'flex-1 h-9 rounded-md border px-3 text-sm font-semibold transition-colors disabled:opacity-50'
  const tabActive = 'bg-neutral-900 border-neutral-700'
  const tabIdle = 'bg-neutral-950 border-neutral-900 hover:border-neutral-700'

  const itemBase = 'w-fit max-w-full text-left text-[11px] border rounded-md px-2 py-1.5 leading-tight transition-colors disabled:opacity-50'
  const itemIdle = 'bg-neutral-950 border-neutral-800 hover:border-neutral-700'
  const itemActive = 'bg-indigo-950/40 border-indigo-700'

  const loadingCardBase = 'rounded-md border border-neutral-800 bg-neutral-950 px-3 py-2 text-xs text-neutral-400'
  const loadingCardPulse = `${loadingCardBase} animate-pulse`
  const searchResultRowClass = 'text-left text-xs bg-neutral-950 border border-neutral-800 rounded-md p-2 hover:border-neutral-700 disabled:opacity-50'
  const confirmDangerClass = 'h-9 rounded-md bg-red-700 hover:bg-red-600 px-3 text-sm font-semibold disabled:opacity-50'
  const confirmCancelClass = 'h-9 rounded-md bg-neutral-900 hover:bg-neutral-800 px-3 text-sm font-semibold disabled:opacity-50'
  const semanticUnavailableText = semanticSearchUnavailableReason === 'missing_api_key'
    ? 'нужен OPENAI_API_KEY'
    : semanticSearchUnavailableReason === 'embeddings_disabled'
      ? 'эмбеддинги отключены'
      : ''

  const HelpButton = ({
    topic,
    label,
  }: {
    topic: 'projects' | 'graph' | 'search'
    label?: string
  }) => (
    <button
      type="button"
      className="w-3.5 h-3.5 rounded-full border border-neutral-800 bg-neutral-900 text-neutral-200 text-[10px] leading-none font-semibold hover:bg-neutral-800 shrink-0"
      onMouseDown={(e) => {
        e.preventDefault()
        e.stopPropagation()
      }}
      onClick={() => setHelpOpen(topic)}
      aria-label={label || 'Открыть подсказку'}
      title={label || 'Подсказка'}
    >
      ?
    </button>
  )

  const SectionHeader = ({
    title,
    topic,
    right,
  }: {
    title: string
    topic?: 'projects' | 'graph' | 'search'
    right?: React.ReactNode
  }) => (
    <div className="flex items-center justify-between gap-3 min-h-6">
      <div className="flex items-center gap-2">
        <div className="text-sm font-semibold text-neutral-200 leading-none">{title}</div>
        {topic ? <HelpButton topic={topic} label={`Help: ${title}`} /> : null}
      </div>
      {right ?? null}
    </div>
  )

  const fmtK = React.useCallback((n: unknown): string => {
    const v = Number(n)
    if (!Number.isFinite(v)) return '—'
    const abs = Math.abs(v)
    if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
    if (abs >= 1_000) return `${Math.round(v / 1_000)}k`
    return String(Math.round(v))
  }, [])

  const isFullyVisibleInContainer = React.useCallback((el: HTMLElement, container: HTMLElement) => {
    const er = el.getBoundingClientRect()
    const cr = container.getBoundingClientRect()
    // fully inside vertical viewport
    return er.top >= cr.top && er.bottom <= cr.bottom
  }, [])

  const ensureVisibleInContainer = React.useCallback(
    (el: HTMLElement, container: HTMLElement) => {
      if (isFullyVisibleInContainer(el, container)) return
      try {
        // "nearest" prevents the annoying re-centering jump
        el.scrollIntoView({ block: 'nearest' })
      } catch {
        // ignore
      }
    },
    [isFullyVisibleInContainer],
  )

  const toNum = React.useCallback((v: unknown): number => {
    const n = Number(v)
    return Number.isFinite(n) ? n : NaN
  }, [])

  type View = 'explorer' | 'manage'
  const [view, setView] = React.useState<View>(() => {
    try {
      const v = (localStorage.getItem('cs.ui.sidebarView') || '').trim()
      return v === 'manage' ? 'manage' : 'explorer'
    } catch {
      return 'explorer'
    }
  })
  React.useEffect(() => {
    try { localStorage.setItem('cs.ui.sidebarView', view) } catch {}
  }, [view])

  const [explorerFilter, setExplorerFilter] = React.useState('')
  const ef = explorerFilter.trim().toLowerCase()

  const MAX_DIRS_PER_NODE = 120
  const MAX_FILES_PER_NODE = 160

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

  // Auto-reveal selected path: open ancestor directories when selection changes.
  React.useEffect(() => {
    if (view !== 'explorer') return
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
  }, [ef, projectFilesBusy, selectedPath, view])

  // Scroll selected item into view (only if needed; avoid "center" jumps and avoid tying to openDirs).
  React.useEffect(() => {
    if (view !== 'explorer') return
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
  }, [ef, ensureVisibleInContainer, projectFilesBusy, selectedPath, view])

  const isSelectedFile = React.useCallback(
    (path: string) => {
      const p = String(path || '').trim()
      const sel = String(selectedPath || '').trim()
      return !!p && !!sel && p === sel
    },
    [selectedPath],
  )

  // Jump (module/file) quick switch
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

  React.useEffect(() => {
    if (view !== 'explorer') return
    if (!activeProject) return
    const key = String(jumpModule || '.')
    if (!key || key === '.') return
    // Ensure module directory is open and visible
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
  }, [activeProject, dirDomId, ensureVisibleInContainer, jumpModule, view])

  const renderFile = (f: ProjectFileItem, depth: number, opts?: { showPath?: boolean }) => {
    const selected = isSelectedFile(f.path)
    const name = f.path.split('/').pop() || f.path
    const showPath = Boolean(opts?.showPath)
    const lang = String((f as any)?.language ?? '—')
    const risk = toNum((f as any)?.risk)
    const loc = toNum((f as any)?.loc)
    const fi = toNum((f as any)?.fan_in)
    const fo = toNum((f as any)?.fan_out)

    const tooltip = [
      f.path,
      `lang: ${lang}`,
      `risk: ${Number.isFinite(risk) ? risk.toFixed(2) : '—'}`,
      `loc: ${Number.isFinite(loc) ? String(loc) : '—'}`,
      `fan_in/out: ${Number.isFinite(fi) ? String(fi) : '—'}/${Number.isFinite(fo) ? String(fo) : '—'}`,
    ].join('\n')
    return (
      <button
        key={f.path}
        id={selected ? 'cs-explorer-selected' : undefined}
        className={[
          itemBase,
          selected ? itemActive : itemIdle,
        ].join(' ')}
        onClick={() => onSelectPath(f.path)}
        onMouseDown={(e) => e.preventDefault()}
        disabled={!activeProject || busy}
        title={tooltip}
        style={{ marginLeft: depth > 0 ? depth * 10 : 0 }}
      >
        <div className="text-neutral-200 truncate">{showPath ? f.path : name}</div>
      </button>
    )
  }

  const renderDir = (d: DirNode, depth: number) => {
    const openDefault = depth === 0
    const isOpen = (openDirs[d.path] ?? openDefault) === true
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
          className="w-full text-left py-2 pr-3 text-xs text-neutral-200 hover:bg-neutral-900"
          onClick={() => toggleDir(d.path)}
          title={dirTooltip}
          style={{ paddingLeft: pad }}
          onMouseDown={(e) => e.preventDefault()}
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
          <div className="px-2 pb-1.5 flex flex-col gap-0.5">
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

  return (
    <div className="relative h-full min-h-0 border-r border-neutral-800 overflow-visible">
      {/* Handle OUTSIDE the panel (into the graph area) */}
      {onHidePanel && (
        <button
          type="button"
          className="absolute -right-2 top-1/2 -translate-y-1/2 z-20 rounded-md bg-neutral-950/80 border border-neutral-700 px-1 py-2 text-xs font-semibold text-neutral-200 hover:bg-neutral-900 shadow-lg"
          onMouseDown={(e) => { e.preventDefault(); e.stopPropagation() }}
          onClick={() => onHidePanel?.()}
          aria-label="Hide left panel"
          title="Hide left panel"
        >
          {'<'}
        </button>
      )}

      {/* Scrollable content */}
      <div className="h-full min-h-0 overflow-auto">
        <div className="p-4 flex flex-col gap-3">
          <div className="text-lg font-semibold">CGRAPH</div>

          <div className="mt-2">
            <SectionHeader title="Project" topic="projects" />
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              className={[
                tabBase,
                view === 'explorer' ? tabActive : tabIdle,
              ].join(' ')}
              onClick={() => setView('explorer')}
              disabled={busy}
              title="Показать дерево файлов и быстрый переход"
            >
              Explorer
            </button>
            <button
              type="button"
              className={[
                tabBase,
                view === 'manage' ? tabActive : tabIdle,
              ].join(' ')}
              onClick={() => setView('manage')}
              disabled={busy}
              title="Управление проектами, графом и поиском"
            >
              Manage
            </button>
          </div>

          {view === 'explorer' && (
            <>
              <div className="mt-2">
                <SectionHeader
                  title="Explorer"
                  right={
                    <button
                      type="button"
                      className={miniButtonClass}
                      onClick={() => {
                        void Promise.resolve(onOpenDocs())
                      }}
                      disabled={!activeProject || busy}
                      title="Открыть документацию проекта (генерируемую backend)"
                    >
                      Docs
                    </button>
                  }
                />
              </div>

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
                    title="Быстрый переход к верхнеуровневой папке (модулю). В списке показаны агрегированные метрики."
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
                    title="Быстрый переход к файлу внутри выбранного модуля"
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

              <input
                className={inputSmClass}
                placeholder="Filter (Path)…"
                value={explorerFilter}
                onChange={(e) => setExplorerFilter(e.target.value)}
                disabled={!activeProject || busy}
                title="Локальный фильтр по дереву файлов (по подстроке пути). Не делает запрос к backend."
              />

              {projectFilesBusy ? (
                <div className={loadingCardBase}>
                  Loading files…
                </div>
              ) : !activeProject ? (
                <div className="text-xs text-neutral-500">Выбери проект.</div>
              ) : (projectFiles?.length || 0) === 0 ? (
                <div className="text-xs text-neutral-500">Нет файлов (сначала Scan).</div>
              ) : (
                <div ref={explorerScrollRef} className="mt-2 max-h-[55vh] overflow-auto flex flex-col gap-0.5">
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
                      {/* root-level files */}
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
            </>
          )}

          {view === 'manage' && (
            <>

          {projectsLoading && projects.length === 0 ? (
            <div className={loadingCardPulse}>
              Загружаем список проектов…
            </div>
          ) : (
            <div className="flex gap-2 w-full">
              <select
                className={selectSmFlexClass}
                value={activeProject?.id ?? ''}
                disabled={busy || projects.length === 0}
                onChange={(e) => {
                  const id = Number(e.target.value)
                  const p = projects.find((x) => x.id === id)
                  if (p) onPickProject(p)
                }}
                title="Выбор активного проекта"
              >
                <option value="" disabled>
                  {projects.length ? 'Выбери проект…' : 'Нет проектов'}
                </option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>

              <button
                type="button"
                className={buttonDanger}
                disabled={!activeProject || busy}
                onClick={() => setConfirmDeleteOpen(true)}
                title="Удалить активный проект (необратимо)"
              >
                Delete
              </button>
            </div>
          )}

          {activeProject && (
            <div className="text-xs text-neutral-400 truncate" title={activeProject.root_path}>
              {activeProject.root_path}
            </div>
          )}

          <div className="mt-3 text-sm font-semibold text-neutral-200">Add</div>
          <input
            className={inputSmClass}
            placeholder="name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            disabled={busy}
            title="Имя проекта (отображаемое в UI)"
          />
          <input
            className={inputSmClass}
            placeholder="/absolute/path/to/repo"
            value={newPath}
            onChange={(e) => setNewPath(e.target.value)}
            disabled={busy}
            title="Абсолютный путь к репозиторию на машине, где запущен backend"
          />
          <div className="text-xs text-neutral-500 leading-relaxed">
            Путь должен быть абсолютным
          </div>
          <button
            className={buttonPrimary}
            onClick={() => onCreateProject()}
            disabled={!newName.trim() || !newPath.trim() || busy}
            title="Создать проект и сохранить root_path"
          >
            Create Project
          </button>

          <div className="mt-4">
            <SectionHeader title="Graph" topic="graph" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs text-neutral-300">
              <div className={labelRowClass}>
                <span className={fieldLabelClass}>Mode</span>
              </div>
              <select
                className={controlClass + ' mt-1'}
                value={graphMode}
                onChange={(e) => setGraphMode(e.target.value as any)}
                disabled={busy || !activeProject}
                title="local — окрестность выбранного файла; full — весь граф; top-N — ограниченный граф из N узлов"
              >
                <option value="local">Local</option>
                <option value="full">Full</option>
                <option value="limit">Top-N</option>
              </select>
            </label>

            <label className="text-xs text-neutral-300">
              <div className={labelRowClass}>
                <span className={fieldLabelClass}>N</span>
              </div>
              <input
                type="number"
                className={controlClass + ' mt-1'}
                value={graphLimitN}
                min={100}
                max={20000}
                step={100}
                disabled={busy || !activeProject || graphMode !== 'limit'}
                onChange={(e) => {
                  const raw = e.target.value
                  const next = raw === '' ? 2000 : clampInt(Number(raw), 100, 20000)
                  setGraphLimitN(next)
                }}
                title="Количество узлов для режима top-N"
              />
            </label>

            <label className="text-xs text-neutral-300">
              <div className={labelRowClass}>
                <span className={fieldLabelClass}>Hops</span>
              </div>
              <input
                type="number"
                className={controlClass + ' mt-1'}
                value={graphHops}
                min={1}
                max={6}
                disabled={busy || !activeProject}
                onChange={(e) => {
                  const raw = e.target.value
                  const next = raw === '' ? 1 : clampInt(Number(raw), 1, 6)
                  setGraphHops(next)
                }}
                title="Глубина связей (hops) для построения графа"
              />
            </label>

            <label className="text-xs text-neutral-300">
              <div className={labelRowClass}>
                <span className={fieldLabelClass}>Max Nodes (Local)</span>
              </div>
              <input
                type="number"
                className={controlClass + ' mt-1'}
                value={graphLocalMax}
                min={50}
                max={2000}
                step={50}
                disabled={busy || !activeProject}
                onChange={(e) => {
                  const raw = e.target.value
                  const next = raw === '' ? 400 : clampInt(Number(raw), 50, 2000)
                  setGraphLocalMax(next)
                }}
                title="Ограничение размера локального графа (для производительности)"
              />
            </label>
          </div>

          <div className="mt-2 flex gap-2">
            <button
              className={buttonSoft}
              onClick={() => onScan()}
              disabled={!activeProject || busy}
              title="Scan: переиндексировать проект и пересчитать зависимости"
            >
              Scan
            </button>
            <button
              className={buttonNeutral}
              onClick={() => onRefresh()}
              disabled={!activeProject || busy}
              title="Refresh: перезагрузить данные графа и панелей"
            >
              Refresh
            </button>
          </div>

          <div className="mt-4">
            <SectionHeader title="File Search" topic="search" />
          </div>
          <label className="mt-2 flex items-center gap-2 text-xs text-neutral-300">
            <input
              type="checkbox"
              checked={semanticSearchEnabled}
              onChange={(e) => setSemanticSearchEnabled(e.target.checked)}
              disabled={!activeProject || busy}
            />
            <span>Semantic search</span>
            {semanticSearchUnavailableReason ? (
              <span className="text-[11px] text-neutral-500">{semanticUnavailableText}</span>
            ) : null}
          </label>
          <div className="flex gap-2">
            <input
              className={inputSmFlexClass}
              placeholder={semanticSearchEnabled ? 'semantic query' : 'path substring'}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') onSearchNodes(searchQuery)
              }}
              disabled={!activeProject || busy}
              title="Поиск по подстроке пути через backend (Enter — искать)"
            />
            <button
              className={buttonSoft}
              onClick={() => onSearchNodes(searchQuery)}
              disabled={!activeProject || busy || searchBusy || !searchQuery.trim()}
              title="Запустить поиск"
            >
              {searchBusy ? '...' : 'Search'}
            </button>
          </div>

          {!semanticSearchEnabled && searchResults.length > 0 && (
            <div className="mt-2 flex flex-col gap-1 max-h-40 overflow-auto">
              {searchResults.map((r) => (
                <button
                  key={r.path}
                  className={searchResultRowClass}
                  onClick={() => onSelectPath(r.path)}
                  onMouseDown={(e) => e.preventDefault()}
                  disabled={!activeProject || busy}
                  title="Выбрать файл (и открыть его в правой панели / Local-графе)"
                >
                  <div className="text-neutral-200 font-semibold">{r.path}</div>
                  <div className="text-neutral-500">{r.language ?? '—'} · In:{r.fan_in ?? 0} · Out:{r.fan_out ?? 0}</div>
                </button>
              ))}
            </div>
          )}

          {semanticSearchEnabled && semanticSearchFallbackUsed && searchResults.length > 0 && (
            <div className="mt-2 flex flex-col gap-1 max-h-40 overflow-auto">
              <div className="text-[11px] text-neutral-500">
                Показан fallback‑поиск по пути
              </div>
              {searchResults.map((r) => (
                <button
                  key={r.path}
                  className={searchResultRowClass}
                  onClick={() => onSelectPath(r.path)}
                  onMouseDown={(e) => e.preventDefault()}
                  disabled={!activeProject || busy}
                  title="Выбрать файл (и открыть его в правой панели / Local-графе)"
                >
                  <div className="text-neutral-200 font-semibold">{r.path}</div>
                  <div className="text-neutral-500">{r.language ?? '—'} · In:{r.fan_in ?? 0} · Out:{r.fan_out ?? 0}</div>
                </button>
              ))}
            </div>
          )}

          {semanticSearchEnabled && searchSemanticResults.length > 0 && (
            <div className="mt-2 flex flex-col gap-1 max-h-40 overflow-auto">
              {searchSemanticResults.map((r, idx) => {
                const score = Number.isFinite(r.score) ? r.score.toFixed(3) : '—'
                return (
                  <button
                    key={`${r.path}-${idx}`}
                    className={searchResultRowClass}
                    onClick={() => onSelectPath(r.path)}
                    onMouseDown={(e) => e.preventDefault()}
                    disabled={!activeProject || busy}
                    title="Выбрать файл (и открыть его в правой панели / Local-графе)"
                  >
                    <div className="text-neutral-200 font-semibold">{r.path}</div>
                    <div className="text-neutral-500">Score: {score}</div>
                    {r.snippet ? (
                      <div className="mt-1 text-[11px] text-neutral-400 whitespace-pre-wrap line-clamp-3">
                        {r.snippet}
                      </div>
                    ) : null}
                  </button>
                )
              })}
            </div>
          )}

          {error && <div className="mt-2 text-xs text-red-300 whitespace-pre-wrap">{error}</div>}
            </>
          )}

          <Modal
            open={helpOpen != null}
            title={
              helpOpen === 'projects' ? 'Подсказка: проекты' : helpOpen === 'graph' ? 'Подсказка: граф' : 'Подсказка: поиск'
            }
            onClose={() => setHelpOpen(null)}
          >
            {helpOpen === 'projects' && (
              <div className="space-y-2">
                <div className="text-neutral-200 font-semibold">Как устроены проекты</div>
                <div>• Project — это корень репозитория (<span className="font-mono">root_path</span>) на машине, где запущен backend.</div>
                <div>• Explorer показывает дерево файлов (локальный фильтр — по подстроке пути).</div>
                <div>• Manage — выбор/создание/удаление проекта, управление графом и поиск файла через backend.</div>
                <div>• Delete удаляет проект и все связанные данные (граф, контракты, история запусков). Операция необратима.</div>
              </div>
            )}
            {helpOpen === 'graph' && (
              <div className="space-y-2">
                <div className="text-neutral-200 font-semibold">Параметры графа</div>
                <div>• Mode:</div>
                <div className="ml-3">— <span className="font-mono">Local</span>: окрестность выбранного файла (нужен выбранный файл).</div>
                <div className="ml-3">— <span className="font-mono">Full</span>: весь граф проекта.</div>
                <div className="ml-3">— <span className="font-mono">Top-N</span>: ограниченный граф из <span className="font-mono">N</span> узлов (по скорингу backend).</div>
                <div>• N используется только для режима <span className="font-mono">Top-N</span>.</div>
                <div>• Hops — глубина связей (сколько «шагов» по ребрам).</div>
                <div>• Max Nodes (Local) — лимит размера локального графа для скорости/читабельности.</div>
                <div className="pt-2">• <span className="font-mono">Scan</span> — переиндексация и пересчёт зависимостей.</div>
                <div>• <span className="font-mono">Refresh</span> — перезагрузка данных графа/панелей без изменения настроек.</div>
              </div>
            )}
            {helpOpen === 'search' && (
              <div className="space-y-2">
                <div className="text-neutral-200 font-semibold">Поиск и фильтрация</div>
                <div>• Manage → «Поиск файла» — запрос к backend по подстроке пути (например, <span className="font-mono">service/</span>).</div>
                <div>• Explorer → «Filter (Path)…» — локальный фильтр по дереву файлов (без запросов).</div>
                <div>• Клик по результату выбирает файл; для <span className="font-mono">local</span>-режима это обязательный шаг.</div>
              </div>
            )}
          </Modal>

          <Modal open={confirmDeleteOpen} title="Удалить проект?" onClose={() => setConfirmDeleteOpen(false)}>
            <div className="space-y-3">
              <div className="text-sm text-neutral-200">
                Будут удалены: граф, узлы/рёбра, контракты и история запусков для этого проекта.
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  className={confirmDangerClass}
                  onClick={async () => {
                    setConfirmDeleteOpen(false)
                    await onDeleteActiveProject()
                  }}
                  title="Подтвердить удаление"
                >
                  Yes, delete
                </button>
                <button
                  type="button"
                  className={confirmCancelClass}
                  onClick={() => setConfirmDeleteOpen(false)}
                  title="Отменить"
                >
                  Cancel
                </button>
              </div>
            </div>
          </Modal>
        </div>
      </div>
    </div>
  )
}
