// frontend/src/ui/components/ExplorerTree.tsx
import React from 'react'
import type { Project, ProjectFileItem, ProjectTreeEntry } from '@/api'
import { ExplorerFileActions } from './ExplorerFileActions'
import { useExplorerTree, type VisibleEntry } from './useExplorerTree'

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

  const {
    explorerScrollRef, explorerFilter, setExplorerFilter, ef, focusedPath, setFocusedPath,
    dirStates, searchResults, searchBusy, openDirs, jumpModule, setJumpModule, jumpFile, setJumpFile,
    modules, jumpFiles, visibleEntries, openEntries, pinnedEntries,
    loadDir, toggleDir, focusEntry, isSelectedFile, toNum, dirDomId, handleTreeKeyDown,
  } = useExplorerTree({
    activeProject, selectedPath, openFilePaths, pinnedPaths, showModuleSelect,
    onSelectPath, onOpenFileEditor, onRegisterFileMeta,
  })
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

      <ExplorerFileActions
        activeProject={activeProject}
        busy={busy}
        selectedPath={selectedPath}
        onCreateFile={onCreateFile}
        onRenameFile={onRenameFile}
        onDeleteFile={onDeleteFile}
        onSelectPath={onSelectPath}
        onOpenFileEditor={onOpenFileEditor}
        compact={compact}
      />

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
