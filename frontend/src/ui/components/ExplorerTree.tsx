// frontend/src/ui/components/ExplorerTree.tsx
import React from 'react'
import type { Project, ProjectFileItem } from '../../api'

type ExplorerTreeProps = {
  activeProject: Project | null
  busy: boolean
  selectedPath: string | null
  dirtyPath?: string | null
  onSelectPath: (path: string) => void | Promise<void>
  onCreateFile: (path: string) => void | Promise<void>
  onRenameFile: (path: string, newPath: string) => void | Promise<void>
  onDeleteFile: (path: string) => void | Promise<void>
  projectFiles: ProjectFileItem[]
  projectFilesMeta: any
  projectFilesBusy: boolean
  showModuleSelect?: boolean
}

export function ExplorerTree({
  activeProject,
  busy,
  selectedPath,
  dirtyPath = null,
  onSelectPath,
  onCreateFile,
  onRenameFile,
  onDeleteFile,
  projectFiles,
  projectFilesMeta,
  projectFilesBusy,
  showModuleSelect = true,
}: ExplorerTreeProps) {
  const explorerScrollRef = React.useRef<HTMLDivElement | null>(null)

  const controlBase = 'w-full h-9 rounded-md bg-neutral-900 border border-neutral-800 px-2 text-xs outline-none'
  const controlDisabled = 'disabled:opacity-50'
  const controlClass = `${controlBase} ${controlDisabled}`
  const labelRowClass = 'flex items-center gap-2 leading-none'
  const fieldLabelClass = 'text-[11px] font-semibold text-neutral-200'
  const inputSmClass = 'w-full h-9 rounded-md bg-neutral-900 border border-neutral-800 px-3 text-sm outline-none disabled:opacity-50'

  const itemBase = 'w-fit max-w-full text-left text-[11px] border rounded-md px-2 py-1.5 leading-tight transition-colors disabled:opacity-50'
  const itemIdle = 'bg-neutral-950 border-neutral-800 hover:border-neutral-700'
  const itemActive = 'bg-indigo-950/40 border-indigo-700'

  const [explorerFilter, setExplorerFilter] = React.useState('')
  const ef = explorerFilter.trim().toLowerCase()

  const MAX_DIRS_PER_NODE = 120
  const MAX_FILES_PER_NODE = 160

  const actionsDisabled = busy || projectFilesBusy || !activeProject
  const selectedFilePath = String(selectedPath || '').trim()
  const renameDisabled = actionsDisabled || !selectedFilePath
  const deleteDisabled = actionsDisabled || !selectedFilePath

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
    const isDirtySelected = selected && !!dirtyPath && dirtyPath === f.path
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
        <div className="flex items-center gap-2 text-neutral-200 truncate">
          <span className="truncate">{showPath ? f.path : name}</span>
          {isDirtySelected && (
            <span className="text-amber-300" aria-label="Unsaved changes" title="Unsaved changes">
              ●
            </span>
          )}
        </div>
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
      )}

      <input
        className={inputSmClass}
        placeholder="Filter (Path)…"
        value={explorerFilter}
        onChange={(e) => setExplorerFilter(e.target.value)}
        disabled={!activeProject || busy}
        title="Локальный фильтр по дереву файлов (по подстроке пути). Не делает запрос к backend."
      />

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
          disabled={actionsDisabled}
          onClick={() => {
            if (actionsDisabled) return
            const nextPath = window.prompt('Новый файл (путь относительно корня проекта):', '')
            if (!nextPath) return
            void Promise.resolve(onCreateFile(nextPath.trim()))
          }}
          title="Создать новый файл"
        >
          Create
        </button>
        <button
          type="button"
          className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
          disabled={renameDisabled}
          onClick={() => {
            if (renameDisabled) return
            const nextPath = window.prompt('Новое имя файла:', selectedFilePath)
            if (!nextPath) return
            void Promise.resolve(onRenameFile(selectedFilePath, nextPath.trim()))
          }}
          title="Переименовать выбранный файл"
        >
          Rename
        </button>
        <button
          type="button"
          className="rounded-md border border-rose-900/70 bg-rose-950/40 px-2 py-1 text-[11px] font-semibold text-rose-100 hover:bg-rose-900/40 disabled:opacity-50"
          disabled={deleteDisabled}
          onClick={() => {
            if (deleteDisabled) return
            const confirmed = window.confirm(
              `Удалить файл "${selectedFilePath}"? Это действие нельзя отменить.`
            )
            if (!confirmed) return
            void Promise.resolve(onDeleteFile(selectedFilePath))
          }}
          title="Удалить выбранный файл"
        >
          Delete
        </button>
      </div>

      {projectFilesBusy ? (
        <div className="rounded-md border border-neutral-800 bg-neutral-950 px-3 py-2 text-xs text-neutral-400">
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
