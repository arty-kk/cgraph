// frontend/src/ui/App.tsx
import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ProjectsSidebar } from './components/ProjectsSidebar'
import { GraphCanvas } from './components/GraphCanvas'
import { NodePanel } from './components/NodePanel'
import { Notifications } from './components/Notifications'
import { FileEditorPane } from './components/FileEditorPane'
import { ExplorerTree } from './components/ExplorerTree'
import { useStubGraphApp } from './useStubGraphApp'
import { CommandPalette } from './components/CommandPalette'
import { Modal } from './components/Modal'

export type AppProps = {
  showDependencies?: boolean
}

export function App({ showDependencies = true }: AppProps) {
  const searchInputRef = React.useRef<HTMLInputElement | null>(null)
  const appRef = React.useRef<ReturnType<typeof useStubGraphApp> | null>(null)
  const [docsOpen, setDocsOpen] = React.useState(false)
  const [onboardOpen, setOnboardOpen] = React.useState(false)
  const [onboardStep, setOnboardStep] = React.useState(0)
  const [editorExplorerOpen, setEditorExplorerOpen] = React.useState(() => {
    try {
      const raw = localStorage.getItem('cs.editor.explorerOpen')
      if (raw === '0') return false
      if (raw === '1') return true
      return true
    } catch {
      return true
    }
  })
  const [editorLeftTab, setEditorLeftTab] = React.useState<'explorer' | 'search'>(() => {
    try {
      const raw = localStorage.getItem('cs.editor.leftTab')
      return raw === 'explorer' || raw === 'search' ? raw : 'explorer'
    } catch {
      return 'explorer'
    }
  })
  const [editorWrap, setEditorWrap] = React.useState(() => {
    try { return (localStorage.getItem('cs.editor.wrap') || '1') !== '0' } catch { return true }
  })
  const [editorShowDiff, setEditorShowDiff] = React.useState(() => {
    try { return (localStorage.getItem('cs.editor.showDiff') || '') === '1' } catch { return false }
  })
  const [editorFontSize, setEditorFontSize] = React.useState(() => {
    try {
      const raw = localStorage.getItem('cs.editor.fontSize')
      const parsed = raw ? Number(raw) : Number.NaN
      return Number.isFinite(parsed) ? parsed : 13
    } catch {
      return 13
    }
  })

  const handleFocusSearch = React.useCallback(() => {
    appRef.current?.setWorkspaceView('editor')
    setEditorLeftTab('search')
    setEditorExplorerOpen(true)
    requestAnimationFrame(() => searchInputRef.current?.focus())
  }, [])

  const app = useStubGraphApp({ onFocusSearch: handleFocusSearch })

  React.useEffect(() => {
    appRef.current = app
  }, [app])

  const pid = app.activeProject?.id
  const onboardKey = pid != null ? `cs.onboarding.seen.${pid}` : null

  React.useEffect(() => {
    if (!pid || !onboardKey) { setOnboardOpen(false); return }
    try {
      const seen = localStorage.getItem(onboardKey) === '1'
      if (!seen) { setOnboardOpen(true); setOnboardStep(0) }
    } catch {}
  }, [pid, onboardKey])

  const closeOnboarding = (markSeen: boolean) => {
    if (markSeen && onboardKey) {
      try { localStorage.setItem(onboardKey, '1') } catch {}
    }
    setOnboardOpen(false)
  }

  const filePathSet = React.useMemo(() => {
    const s = new Set<string>()
    for (const f of app.projectFiles || []) {
      const p = String((f as any)?.path ?? '').trim()
      if (p) s.add(p)
    }
    return s
  }, [app.projectFiles])

  const editorTabs = React.useMemo(() => {
    return (app.openFilePaths || []).map((path) => {
      const entry = app.fileEditorsByPath?.[path]
      const dirty = entry ? entry.content !== entry.original : false
      return { path, dirty }
    })
  }, [app.fileEditorsByPath, app.openFilePaths])

  const hasDirtyTabs = React.useMemo(() => {
    return (app.openFilePaths || []).some((path) => {
      const entry = app.fileEditorsByPath?.[path]
      return entry ? entry.content !== entry.original : false
    })
  }, [app.fileEditorsByPath, app.openFilePaths])

  const canCloseAllTabs = (app.openFilePaths || []).length > 0
  const canCloseOtherTabs = Boolean(app.activeFilePath && (app.openFilePaths || []).length > 1)
  const canCloseTabsToRight = React.useMemo(() => {
    if (!app.activeFilePath) return false
    const index = (app.openFilePaths || []).indexOf(app.activeFilePath)
    return index >= 0 && index < (app.openFilePaths || []).length - 1
  }, [app.activeFilePath, app.openFilePaths])

  const activeFileMeta = React.useMemo(() => {
    if (!app.activeFilePath) return null
    return app.projectFiles?.find((file) => file.path === app.activeFilePath) ?? null
  }, [app.activeFilePath, app.projectFiles])

  const activeFileDependencies = React.useMemo(() => {
    const inSet = new Set<string>()
    const outSet = new Set<string>()
    if (!app.graph || !app.activeFilePath) return { in: [] as string[], out: [] as string[] }

    const keyToPath = new Map<string, string>()
    for (const n of app.graph.nodes || []) {
      const id = typeof (n as any)?.id === 'string' ? String((n as any).id) : ''
      const path = typeof (n as any)?.path === 'string' ? String((n as any).path) : ''
      if (path) keyToPath.set(path, path)
      if (id && path) keyToPath.set(id, path)
      if (id && !keyToPath.has(id)) keyToPath.set(id, id)
    }

    const selNode =
      (app.graph.nodes || []).find((n: any) => n?.path === app.activeFilePath || n?.id === app.activeFilePath) ?? null
    const selId = selNode && typeof (selNode as any).id === 'string' ? String((selNode as any).id) : null

    const isSel = (k: string) => k === app.activeFilePath || (selId != null && k === selId)
    const toPath = (k: string) => keyToPath.get(k) || k

    for (const e of app.graph.edges || []) {
      const s = typeof (e as any)?.source === 'string' ? String((e as any).source) : ''
      const t = typeof (e as any)?.target === 'string' ? String((e as any).target) : ''
      if (!s || !t) continue
      if (isSel(t)) inSet.add(toPath(s))
      if (isSel(s)) outSet.add(toPath(t))
    }

    const inbound = Array.from(inSet).filter(Boolean).sort()
    const outbound = Array.from(outSet).filter(Boolean).sort()
    return { in: inbound, out: outbound }
  }, [app.activeFilePath, app.graph])

  const totalIn = activeFileDependencies.in.length
  const totalOut = activeFileDependencies.out.length

  const confirmTitle = app.confirmReason === 'reload-file' ? 'Reload file?' : 'Unsaved changes'
  const confirmBody =
    app.confirmReason === 'reload-file'
      ? 'Reloading the file will discard unsaved changes.'
      : 'You have unsaved changes.'

  const clampFontSize = React.useCallback((value: number) => Math.min(16, Math.max(12, value)), [])

  React.useEffect(() => {
    setEditorFontSize((prev) => clampFontSize(prev))
  }, [clampFontSize])

  React.useEffect(() => {
    try { localStorage.setItem('cs.editor.wrap', editorWrap ? '1' : '0') } catch {}
  }, [editorWrap])

  React.useEffect(() => {
    try { localStorage.setItem('cs.editor.explorerOpen', editorExplorerOpen ? '1' : '0') } catch {}
  }, [editorExplorerOpen])

  React.useEffect(() => {
    try { localStorage.setItem('cs.editor.leftTab', editorLeftTab) } catch {}
  }, [editorLeftTab])

  React.useEffect(() => {
    try { localStorage.setItem('cs.editor.showDiff', editorShowDiff ? '1' : '0') } catch {}
  }, [editorShowDiff])

  React.useEffect(() => {
    try { localStorage.setItem('cs.editor.fontSize', String(editorFontSize)) } catch {}
  }, [editorFontSize])

  const activeFileDirty = React.useMemo(() => {
    if (!app.activeFilePath) return false
    const entry = app.fileEditorsByPath?.[app.activeFilePath]
    return entry ? entry.content !== entry.original : false
  }, [app.activeFilePath, app.fileEditorsByPath])

  const quickSummaryDisabledReason = React.useMemo(() => {
    if (!app.activeProject) return 'Select a project to run a quick summary.'
    if (!app.selectedPath) return 'Select a file to summarize.'
    if (!app.nodeInfo && !app.contract) return 'Loading file info...'
    if (app.busy || app.nodeBusy) return 'Please wait for the current operation to finish.'
    return ''
  }, [app.activeProject, app.selectedPath, app.nodeInfo, app.contract, app.busy, app.nodeBusy])

  const canQuickSummary = quickSummaryDisabledReason === ''

  const canSaveEditor = Boolean(
    app.fileEditorOpen
    && app.activeFilePath
    && app.fileEditorDirty
    && !app.fileEditorTruncated
    && !app.fileEditorBusy
    && !app.fileEditorSaving
  )
  const showEditorEmptyState = !app.fileEditorOpen || !app.activeFilePath || editorTabs.length === 0

  const totalOnboardSteps = 4
  const onboardSteps = [
    {
      title: 'Scan the project',
      description: 'Index the project so the graph can build relationships.',
      tip: 'Scan — слева в тулбаре.',
      action: {
        label: 'Scan now',
        onClick: () => void app.onScan(),
        disabled: !app.activeProject || app.busy,
        variant: 'primary',
      },
    },
    {
      title: 'Open the palette',
      description: 'Pick a file quickly and jump to it.',
      tip: 'Palette — Ctrl/⌘+K.',
      action: {
        label: 'Open palette',
        onClick: () => app.setPaletteOpen(true),
        disabled: false,
        variant: 'secondary',
      },
    },
    {
      title: 'Explore the graph',
      description: 'Click a node to center it and highlight its edges.',
      tip: 'Graph — центр.',
    },
    {
      title: 'Run a task',
      description: 'Pick a chip or write a prompt, then press Run.',
      tip: 'Tasks — справа.',
    },
  ]

  const handleIncreaseFontSize = React.useCallback(() => {
    setEditorFontSize((prev) => clampFontSize(prev + 1))
  }, [clampFontSize])

  const handleDecreaseFontSize = React.useCallback(() => {
    setEditorFontSize((prev) => clampFontSize(prev - 1))
  }, [clampFontSize])

  const handleSetFontSize = React.useCallback((value: number) => {
    setEditorFontSize(clampFontSize(value))
  }, [clampFontSize])

  const openDocs = React.useCallback(() => {
    if (!app.activeProject) return
    setDocsOpen(true)
    void app.loadDocs()
  }, [app.activeProject, app.loadDocs])

  React.useEffect(() => {
    if (!docsOpen) return
    if (!app.activeProject) { setDocsOpen(false); return }
    void app.loadDocs()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [app.activeProject?.id, docsOpen])

  const gridTemplateColumns = React.useMemo(() => {
    if (app.workspaceView !== 'graph') return '1fr'
    if (app.focusGraph) return '1fr'
    const w = 320
    const left = app.leftPanelOpen ? `${w}px ` : ''
    const right = app.rightPanelOpen ? ` ${w}px` : ''
    return `${left}1fr${right}`.trim()
  }, [app.compactMode, app.focusGraph, app.leftPanelOpen, app.rightPanelOpen, app.workspaceView])

  return (
    <div className="h-screen w-screen overflow-hidden relative bg-neutral-950 text-neutral-100">
      <div className="h-screen w-screen overflow-x-hidden grid min-w-0" style={{ gridTemplateColumns, gridTemplateRows: '1fr' }}>

      {app.workspaceView === 'graph' && !app.focusGraph && app.leftPanelOpen && (
          <ProjectsSidebar
            onHidePanel={app.toggleLeftPanel}
            projects={app.projects}
            activeProject={app.activeProject}
            openFilePaths={app.openFilePaths}
            activeFilePath={app.activeFilePath}
            selectedPath={app.selectedPath}
            projectsLoading={app.projectsLoading}
            newName={app.newName}
            newPath={app.newPath}
            busy={app.busy}
            error={app.error}
            onPickProject={app.onPickProject}
            onCreateProject={app.onCreateProject}
            onDeleteActiveProject={app.onDeleteActiveProject}
            onScan={app.onScan}
            onRefresh={app.onRefresh}
            setNewName={app.setNewName}
            setNewPath={app.setNewPath}
            onCreateFile={app.onCreateFile}
            onRenameFile={app.onRenameFile}
            onDeleteFile={app.onDeleteFile}
            onOpenFileEditor={(path) => {
              app.setWorkspaceView('editor')
              void Promise.resolve(app.openFileEditor(path))
            }}
            graphMode={app.graphMode}
            graphLimitN={app.graphLimitN}
            setGraphMode={app.setGraphMode}
            setGraphLimitN={app.setGraphLimitN}
            graphHops={app.graphHops}
            graphLocalMax={app.graphLocalMax}
            setGraphHops={app.setGraphHops}
            setGraphLocalMax={app.setGraphLocalMax}
            searchQuery={app.searchQuery}
            setSearchQuery={app.setSearchQuery}
            searchResults={app.searchResults}
            searchSemanticResults={app.searchSemanticResults}
            semanticSearchFallbackUsed={app.semanticSearchFallbackUsed}
            semanticSearchEnabled={app.semanticSearchEnabled}
            semanticSearchUnavailableReason={app.semanticSearchUnavailableReason}
            setSemanticSearchEnabled={app.setSemanticSearchEnabled}
            searchBusy={app.searchBusy}
            onSearchNodes={app.onSearchNodes}
            onSelectPath={app.onSelectNodePath}
            projectFiles={app.projectFiles}
            projectFilesMeta={app.projectFilesMeta}
            projectFilesBusy={app.projectFilesBusy}
            pinnedPaths={app.pinnedPaths}
            onOpenDocs={openDocs}
          />
        )}

        <div className="min-w-0 min-h-0">
          {app.workspaceView === 'graph' ? (
            <GraphCanvas
              graph={app.graph}
              activeProject={app.activeProject}
              busy={app.busy || app.graphBusy}
              graphMode={app.graphMode}
              selectedPath={app.selectedPath}
              workspaceView={app.workspaceView}
              onBackgroundTap={app.onGraphBackgroundTap}
              onNodeTap={app.onGraphNodeTap}
              onScan={app.onScan}
              onRefresh={app.onRefresh}
              onOpenPalette={() => app.setPaletteOpen(true)}
              notifyInfo={app.notifyInfo}
              onQuickSummary={app.onQuickSummary}
              canQuickSummary={canQuickSummary}
              quickSummaryDisabledReason={quickSummaryDisabledReason}
              compactMode={app.compactMode}
              focusGraph={app.focusGraph}
              setFocusGraph={app.setFocusGraph}
              leftPanelOpen={app.leftPanelOpen}
              rightPanelOpen={app.rightPanelOpen}
              onToggleLeftPanel={app.toggleLeftPanel}
              onToggleRightPanel={app.toggleRightPanel}
              onClearSelection={app.onClearSelection}
              canGoBack={app.canGoBack}
              canGoForward={app.canGoForward}
              onBack={app.goBack}
              onForward={app.goForward}
              selectionTrail={app.selectionTrail}
              onNavigatePath={app.onSelectNodePath}
              pinnedPaths={app.pinnedPaths}
              isSelectedPinned={app.isSelectedPinned}
              onTogglePinSelected={app.togglePinSelected}
              onTogglePinPath={app.togglePinPath}
              onUnpin={app.unpinPath}
              onClearPins={app.clearPins}
              onOpenFileEditor={(path) => {
                app.setWorkspaceView('editor')
                void Promise.resolve(app.openFileEditor(path))
              }}
              onToggleWorkspaceView={app.toggleWorkspaceView}
              onRegisterUndoRedo={app.registerUndoRedoHandlers}
            />
          ) : (
            <div className="h-full w-full overflow-hidden flex relative">
              {app.workspaceView === 'editor' && editorExplorerOpen && (
                <div className="w-72 shrink-0 border-r border-neutral-800 bg-neutral-950/70 flex flex-col">
                  <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-neutral-800">
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        className={[
                          'rounded-md px-2 py-1 text-[11px] font-semibold',
                          editorLeftTab === 'explorer'
                            ? 'bg-neutral-800 text-neutral-100'
                            : 'bg-neutral-900 text-neutral-400 hover:text-neutral-200',
                        ].join(' ')}
                        onClick={() => setEditorLeftTab('explorer')}
                      >
                        Explorer
                      </button>
                      <button
                        type="button"
                        className={[
                          'rounded-md px-2 py-1 text-[11px] font-semibold',
                          editorLeftTab === 'search'
                            ? 'bg-neutral-800 text-neutral-100'
                            : 'bg-neutral-900 text-neutral-400 hover:text-neutral-200',
                        ].join(' ')}
                        onClick={() => setEditorLeftTab('search')}
                      >
                        Search
                      </button>
                    </div>
                    <button
                      type="button"
                      className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800"
                      onClick={() => setEditorExplorerOpen(false)}
                      aria-label="Hide explorer"
                      title="Hide explorer"
                    >
                      {'<'}
                    </button>
                  </div>
                  <div className="p-3 overflow-auto">
                    {editorLeftTab === 'explorer' ? (
                      <ExplorerTree
                        activeProject={app.activeProject}
                        busy={app.busy}
                        openFilePaths={app.openFilePaths}
                        activeFilePath={app.activeFilePath}
                        selectedPath={app.selectedPath}
                        dirtyPath={activeFileDirty ? app.activeFilePath : null}
                        onSelectPath={app.onSelectNodePath}
                        onCreateFile={app.onCreateFile}
                        onRenameFile={app.onRenameFile}
                        onDeleteFile={app.onDeleteFile}
                        onOpenFileEditor={(path) => {
                          app.setWorkspaceView('editor')
                          void Promise.resolve(app.openFileEditor(path))
                        }}
                        projectFiles={app.projectFiles}
                        projectFilesMeta={app.projectFilesMeta}
                        projectFilesBusy={app.projectFilesBusy}
                        pinnedPaths={app.pinnedPaths}
                        showModuleSelect={false}
                        compact
                        showOpenEditors={false}
                      />
                    ) : (
                      <div className="space-y-3">
                        <div className="space-y-2">
                          <label className="text-xs text-neutral-400">Query</label>
                          <input
                            ref={searchInputRef}
                            type="text"
                            value={app.textSearchQuery}
                            onChange={(e) => app.setTextSearchQuery(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') void app.onSearchText(app.textSearchQuery)
                            }}
                            placeholder="Find in project..."
                            className="w-full rounded-md border border-neutral-800 bg-neutral-950 px-2 py-1 text-xs text-neutral-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                          />
                        </div>
                        <div className="space-y-2">
                          <label className="text-xs text-neutral-400">Prefix</label>
                          <input
                            type="text"
                            value={app.textSearchPrefix}
                            onChange={(e) => app.setTextSearchPrefix(e.target.value)}
                            placeholder="Optional path prefix"
                            className="w-full rounded-md border border-neutral-800 bg-neutral-950 px-2 py-1 text-xs text-neutral-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                          />
                        </div>
                        <div className="flex items-center justify-between gap-2">
                          <button
                            type="button"
                            className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-xs font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
                            onClick={() => void app.onSearchText(app.textSearchQuery)}
                            disabled={!app.activeProject || app.textSearchBusy || !app.textSearchQuery.trim()}
                          >
                            {app.textSearchBusy ? '...' : 'Search'}
                          </button>
                          <label className="flex items-center gap-2 text-[11px] text-neutral-300">
                            <input
                              type="checkbox"
                              checked={app.textSearchCaseSensitive}
                              onChange={(e) => app.setTextSearchCaseSensitive(e.target.checked)}
                              className="accent-indigo-500"
                            />
                            Case sensitive
                          </label>
                        </div>
                        {app.textSearchError && (
                          <div className="rounded-md border border-rose-900/60 bg-rose-950/40 px-2 py-1 text-[11px] text-rose-200">
                            {app.textSearchError}
                          </div>
                        )}
                        {app.textSearchMeta?.message && (
                          <div className="rounded-md border border-amber-800/60 bg-amber-950/30 px-2 py-1 text-[11px] text-amber-200">
                            {app.textSearchMeta.message}
                          </div>
                        )}
                        {app.textSearchMeta && (
                          <div className="text-[11px] text-neutral-500">
                            Scanned {app.textSearchMeta.scanned_files} files, matched {app.textSearchMeta.matched_files}.
                          </div>
                        )}
                        {app.textSearchResults.length === 0 && app.textSearchQuery.trim() && !app.textSearchBusy && !app.textSearchError && (
                          <div className="text-[11px] text-neutral-500">No matches yet.</div>
                        )}
                        <div className="space-y-2">
                          {app.textSearchResults.map((match, idx) => (
                            <button
                              key={`${match.path}:${match.line}:${match.col}:${idx}`}
                              type="button"
                              onClick={() => void app.openFileEditorAt(match.path, match.line, match.col)}
                              className="w-full text-left text-xs bg-neutral-950 border border-neutral-800 rounded-md p-2 hover:border-neutral-700"
                            >
                              <div className="text-[11px] text-neutral-400">
                                {match.path} · Ln {match.line}, Col {match.col}
                                {match.truncated_file && (
                                  <span className="ml-2 text-[10px] text-amber-300">truncated</span>
                                )}
                              </div>
                              <div className="text-[11px] text-neutral-200 font-mono whitespace-pre-wrap">
                                {match.snippet}
                              </div>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              <div className="flex-1 min-w-0 h-full min-h-0 flex flex-col p-4">
                <div className="flex-1 min-h-0">
                  {showEditorEmptyState ? (
                    <div className="h-full w-full rounded-lg border border-neutral-800 bg-neutral-950/70 p-6 flex flex-col items-center justify-center text-center gap-4">
                      <div className="space-y-2 max-w-md">
                        <div className="text-sm font-semibold text-neutral-100">Редактируйте быстрее</div>
                        <p className="text-xs text-neutral-400">
                          Редактируйте файлы, ищите по проекту и просматривайте историю правок.
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center justify-center gap-2">
                        <button
                          type="button"
                          className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2 text-xs font-semibold text-neutral-200 hover:bg-neutral-800"
                          onClick={() => app.setPaletteOpen(true)}
                        >
                          Открыть файл (Ctrl/⌘+K)
                        </button>
                        <button
                          type="button"
                          className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2 text-xs font-semibold text-neutral-200 hover:bg-neutral-800"
                          onClick={handleFocusSearch}
                        >
                          Поиск по проекту (Ctrl/⌘+Shift+F)
                        </button>
                        <button
                          type="button"
                          className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2 text-xs font-semibold text-neutral-200 hover:bg-neutral-800"
                          onClick={() => app.setWorkspaceView('graph')}
                        >
                          Вернуться к графу (Ctrl/⌘+Shift+G)
                        </button>
                      </div>
                    </div>
                  ) : (
                    <FileEditorPane
                      open={app.fileEditorOpen}
                      path={app.activeFilePath}
                      tabs={editorTabs}
                      activePath={app.activeFilePath}
                      nodeInfo={app.nodeInfo}
                      fileMeta={activeFileMeta}
                      original={app.fileEditorOriginal}
                      content={app.fileEditorContent}
                      busy={app.fileEditorBusy}
                      saving={app.fileEditorSaving}
                      dirty={app.fileEditorDirty}
                      truncated={app.fileEditorTruncated}
                      error={app.fileEditorError}
                      wrap={editorWrap}
                      showDiff={editorShowDiff}
                      fontSize={editorFontSize}
                      pendingJump={app.pendingJump}
                      gotoLineRequestId={app.gotoLineRequestId}
                      findRequestId={app.findRequestId}
                      replaceRequestId={app.replaceRequestId}
                      outlineRequestId={app.outlineRequestId}
                      onApplyPendingJump={app.clearPendingJump}
                      onSelectTab={(path) => void app.openFileEditor(path)}
                      onCloseTab={(path) => app.closeFileEditor(path)}
                      onChange={app.setFileEditorContent}
                      onReload={app.requestReloadFileEditor}
                      onSave={app.saveFileEditor}
                      onClose={() => app.setWorkspaceView('graph')}
                      onToggleWrap={() => setEditorWrap((prev) => !prev)}
                      onToggleDiff={() => setEditorShowDiff((prev) => !prev)}
                      onSetFontSize={handleSetFontSize}
                      onFindInFile={app.requestFindInFile}
                      onReplaceInFile={app.requestReplaceInFile}
                      onGoToSymbol={app.requestOutlineInFile}
                      onOpenInGraph={(path) => {
                        app.onSelectNodePath(path)
                        app.setWorkspaceView('graph')
                      }}
                      showDependencies={showDependencies}
                      dependencies={activeFileDependencies}
                      totalIn={totalIn}
                      totalOut={totalOut}
                      onOpenDependencyInGraph={(path) => {
                        app.onSelectNodePath(path)
                        app.setWorkspaceView('graph')
                      }}
                      onOpenDependencyFile={(path) => {
                        app.setWorkspaceView('editor')
                        void Promise.resolve(app.openFileEditor(path))
                      }}
                    />
                  )}
                </div>
              </div>

              {app.workspaceView === 'editor' && !editorExplorerOpen && (
                <button
                  type="button"
                  className="absolute left-2 top-1/2 -translate-y-1/2 z-[95] rounded-r-md bg-neutral-950/90 border border-neutral-700 px-1 py-2 text-xs font-semibold text-neutral-200 hover:bg-neutral-900 shadow-lg"
                  onMouseDown={(e) => { e.preventDefault(); e.stopPropagation() }}
                  onClick={() => setEditorExplorerOpen(true)}
                  aria-label="Show explorer"
                  title="Show explorer"
                >
                  {'>'}
                </button>
              )}
            </div>
          )}
        </div>

        {app.workspaceView === 'graph' && !app.focusGraph && app.rightPanelOpen && (
          <NodePanel
            onHidePanel={app.toggleRightPanel}
            activeProject={app.activeProject}
            selectedPath={app.selectedPath}
            selectedInGraph={app.selectedInGraph}
            graphTruncated={Boolean(app.graph?.meta?.truncated || (app.graph?.meta?.limit_nodes ?? 0) > 0)}
            onLoadFullGraph={app.onLoadFullGraph}
            notifyInfo={app.notifyInfo}
            onScan={app.onScan}
            nodeBusy={app.nodeBusy}
            nodeInfo={app.nodeInfo}
            contract={app.contract}
            graphPreview={app.graphPreview}
            graphPreviewBusy={app.graphPreviewBusy}
            graphPreviewError={app.graphPreviewError}
            busy={app.busy}
            mode={app.mode}
            depth={app.depth}
            depMode={app.depMode}
            retrievalMode={app.retrievalMode}
            agenticMaxCalls={app.agenticMaxCalls}
            agenticMaxFileChars={app.agenticMaxFileChars}
            agenticMaxTotalToolOutputChars={app.agenticMaxTotalToolOutputChars}
            agenticTemperature={app.agenticTemperature}
            agenticEvidenceMode={app.agenticEvidenceMode}
            packMaxFiles={app.packMaxFiles}
            packMaxCharsPerFile={app.packMaxCharsPerFile}
            packMaxTotalChars={app.packMaxTotalChars}
            applyPatch={app.applyPatch}
            prompt={app.prompt}
            setMode={app.setMode}
            setDepth={app.setDepth}
            setDepMode={app.setDepMode}
            setRetrievalMode={app.setRetrievalMode}
            setAgenticMaxCalls={app.setAgenticMaxCalls}
            setAgenticMaxFileChars={app.setAgenticMaxFileChars}
            setAgenticMaxTotalToolOutputChars={app.setAgenticMaxTotalToolOutputChars}
            setAgenticTemperature={app.setAgenticTemperature}
            setAgenticEvidenceMode={app.setAgenticEvidenceMode}
            setPackMaxFiles={app.setPackMaxFiles}
            setPackMaxCharsPerFile={app.setPackMaxCharsPerFile}
            setPackMaxTotalChars={app.setPackMaxTotalChars}
            setApplyPatch={app.setApplyPatch}
            setPrompt={app.setPrompt}
            canRun={app.canRun}
            onRun={app.onRun}
            onRunWithExpandedContext={app.onRunWithExpandedContext}
            runResult={app.runResult}
            fullPatch={app.fullPatch}
            patchBusy={app.patchBusy}
            runLoadBusy={app.runLoadBusy}
            onLoadFullPatch={app.onLoadFullPatch}
            onApplyRunPatch={app.onApplyRunPatch}
            onLoadRun={app.onLoadRun}
            onDeleteRun={app.onDeleteRun}
            runs={app.runs}
            onOpenFileEditor={(path) => {
              app.setWorkspaceView('editor')
              void Promise.resolve(app.openFileEditor(path))
            }}
            setWorkspaceView={app.setWorkspaceView}
          />
        )}
      </div>

      <Notifications notifications={app.notifications} onDismiss={app.dismissNotification} />

      <CommandPalette
        open={app.paletteOpen}
        onClose={() => app.setPaletteOpen(false)}
        projects={app.projects}
        activeProject={app.activeProject}
        onPickProject={app.onPickProject}
        selectedPath={app.selectedPath}
        onSelectPath={app.onSelectNodePath}
        onTogglePinPath={app.togglePinPath}
        openFilePaths={app.openFilePaths}
        selectionTrail={app.selectionTrail}
        pinnedPaths={app.pinnedPaths}
        onScan={app.onScan}
        onRefresh={app.onRefresh}
        onOpenDocs={openDocs}
        focusGraph={app.focusGraph}
        setFocusGraph={app.setFocusGraph}
        onClearSelection={app.onClearSelection}
        canGoBack={app.canGoBack}
        canGoForward={app.canGoForward}
        onBack={app.goBack}
        onForward={app.goForward}
        compactMode={app.compactMode}
        onToggleCompactMode={app.toggleCompactMode}
        editorOpen={app.fileEditorOpen}
        activeFilePath={app.activeFilePath}
        canSave={canSaveEditor}
        canSaveAll={hasDirtyTabs}
        onSave={app.saveFileEditor}
        onSaveAll={app.saveAllOpenFiles}
        onCloseTab={(path) => app.closeFileEditor(path)}
        canCloseAllTabs={canCloseAllTabs}
        onCloseAllTabs={app.closeAllTabs}
        canCloseOtherTabs={canCloseOtherTabs}
        onCloseOtherTabs={(path) => app.closeOtherTabs(path)}
        canCloseTabsToRight={canCloseTabsToRight}
        onCloseTabsToRight={(path) => app.closeTabsToRight(path)}
        onToggleWrap={() => setEditorWrap((prev) => !prev)}
        onToggleDiff={() => setEditorShowDiff((prev) => !prev)}
        onIncreaseFontSize={handleIncreaseFontSize}
        onDecreaseFontSize={handleDecreaseFontSize}
        onToggleExplorer={() => setEditorExplorerOpen((prev) => !prev)}
        onToggleWorkspaceView={app.toggleWorkspaceView}
        onFindInFile={app.requestFindInFile}
        onReplaceInFile={app.requestReplaceInFile}
        onGoToSymbol={app.requestOutlineInFile}
        onOpenFileEditor={(path) => {
          app.setWorkspaceView('editor')
          void Promise.resolve(app.openFileEditor(path))
        }}
      />

      <Modal
        open={app.confirmOpen}
        title={confirmTitle}
        onClose={app.confirmCancel}
      >
        <div className="space-y-4">
          <div className="text-sm text-neutral-200">{confirmBody}</div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 px-3 py-2 text-sm font-semibold disabled:opacity-50"
              onClick={() => void app.confirmCancel()}
              disabled={app.fileEditorSaving || app.fileEditorBusy}
            >
              Cancel
            </button>
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 px-3 py-2 text-sm font-semibold disabled:opacity-50"
              onClick={() => void app.confirmDiscard()}
              disabled={app.fileEditorSaving || app.fileEditorBusy}
            >
              Continue without saving
            </button>
            <button
              type="button"
              className="rounded-md bg-indigo-600 hover:bg-indigo-500 px-3 py-2 text-sm font-semibold disabled:opacity-50"
              onClick={() => void app.confirmSave()}
              disabled={app.fileEditorSaving || app.fileEditorBusy}
            >
              Save
            </button>
          </div>
        </div>
      </Modal>

      <Modal open={docsOpen && !!app.activeProject} title="Project docs" onClose={() => setDocsOpen(false)}>
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="rounded-md bg-neutral-800 hover:bg-neutral-700 px-3 py-2 text-sm font-semibold disabled:opacity-50"
              onClick={() => void app.buildDocs()}
              disabled={!app.activeProject || app.busy || app.docsBuildBusy}
            >
              {app.docsBuildBusy ? 'Building…' : 'Build docs'}
            </button>
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 px-3 py-2 text-sm font-semibold disabled:opacity-50"
              onClick={() => void app.loadDocs()}
              disabled={!app.activeProject || app.busy || app.docsBusy}
            >
              {app.docsBusy ? 'Loading…' : 'Reload'}
            </button>
          </div>

          <div className="text-xs text-neutral-500">
            {app.docs?.created_at ? `Updated: ${app.docs.created_at}` : 'No docs yet'}
          </div>

          <div className="text-xs bg-neutral-950 border border-neutral-800 rounded-md p-3 overflow-auto max-h-[70vh]">
            {app.docsBuildError && app.docs?.markdown && (
              <div className="text-amber-200 bg-amber-500/10 border border-amber-500/30 rounded-md p-2 mb-3">
                Docs failed to update due to an error — showing the previous version.
              </div>
            )}
            {!app.docs?.markdown ? (
              <div className="text-neutral-500">—</div>
            ) : (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  h1: ({ children }) => (
                    <h1 className="text-base font-semibold text-neutral-100 mt-1 mb-2">{children}</h1>
                  ),
                  h2: ({ children }) => (
                    <h2 className="text-sm font-semibold text-neutral-100 mt-4 mb-2">{children}</h2>
                  ),
                  h3: ({ children }) => (
                    <h3 className="text-xs font-semibold text-neutral-100 mt-3 mb-2">{children}</h3>
                  ),
                  p: ({ children }) => <p className="text-xs text-neutral-200 leading-relaxed my-2">{children}</p>,
                  ul: ({ children }) => <ul className="list-disc pl-5 my-2 space-y-1">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal pl-5 my-2 space-y-1">{children}</ol>,
                  li: ({ children }) => <li className="text-xs text-neutral-200">{children}</li>,
                  pre: ({ children }) => (
                    <pre className="text-xs bg-neutral-950 border border-neutral-800 rounded-md p-2 overflow-auto my-2">
                      {children}
                    </pre>
                  ),
                  table: ({ children }) => (
                    <div className="my-3 overflow-auto">
                      <table className="w-full text-xs border-collapse">{children}</table>
                    </div>
                  ),
                  thead: ({ children }) => <thead className="bg-neutral-900/40">{children}</thead>,
                  th: ({ children }) => (
                    <th className="border border-neutral-800 px-2 py-1 text-left text-neutral-200 font-semibold align-top">
                      {children}
                    </th>
                  ),
                  td: ({ children }) => (
                    <td className="border border-neutral-800 px-2 py-1 text-neutral-200 align-top">{children}</td>
                  ),
                  code: ({ children, className }) => {
                    const isInline = !(className && /\blanguage-/.test(className))

                    const text =
                      typeof children === 'string'
                        ? children.trim()
                        : Array.isArray(children)
                          ? String(children[0] ?? '').trim()
                          : String(children ?? '').trim()

                    if (isInline && text && filePathSet.has(text)) {
                      return (
                        <button
                          type="button"
                          className="font-mono text-[11px] rounded border border-neutral-800 bg-neutral-900 px-1 py-0.5 text-indigo-300 hover:underline"
                          title="Open file"
                          onClick={() => {
                            setDocsOpen(false)
                            void Promise.resolve(app.onSelectNodePath(text))
                          }}
                        >
                          {text}
                        </button>
                      )
                    }

                    if (isInline) {
                      return (
                        <code
                          className={[
                            'font-mono text-[11px] rounded border border-neutral-800 bg-neutral-900 px-1 py-0.5',
                            className || '',
                          ].join(' ')}
                        >
                          {children}
                        </code>
                      )
                    }

                    return (
                      <code className={['font-mono text-[11px]', className || ''].join(' ')}>
                        {children}
                      </code>
                    )
                  },
                  a: ({ href, children }) => {
                    const h = String(href || '').trim()
                    if (h.startsWith('file:')) {
                      const p = h.slice('file:'.length).replace(/^\/+/, '').trim()
                      if (p && filePathSet.has(p)) {
                        return (
                          <button
                            type="button"
                            className="text-indigo-300 hover:underline"
                            onClick={() => {
                              setDocsOpen(false)
                              void Promise.resolve(app.onSelectNodePath(p))
                            }}
                          >
                            {children}
                          </button>
                        )
                      }
                    }
                    return (
                      <a
                        href={h || '#'}
                        className="text-indigo-300 hover:underline"
                        target="_blank"
                        rel="noreferrer"
                      >
                        {children}
                      </a>
                    )
                  },
                }}
              >
                {app.docs.markdown}
              </ReactMarkdown>
            )}
          </div>
        </div>
      </Modal>

      <Modal open={onboardOpen && !!app.activeProject} title="Getting started" onClose={() => closeOnboarding(false)}>
        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex-1 space-y-2">
              <div className="flex items-center gap-2 text-neutral-200">
                <span>Step {onboardStep + 1}/{totalOnboardSteps}</span>
                <div className="flex items-center gap-1">
                  {onboardSteps.map((_, index) => {
                    const isActive = index === onboardStep
                    return (
                      <span
                        key={`step-dot-${index}`}
                        className={`h-2 w-2 rounded-full ${isActive ? 'bg-indigo-400' : 'bg-neutral-700'}`}
                      />
                    )
                  })}
                </div>
              </div>
              <div className="h-1 w-full rounded-full bg-neutral-800">
                <div
                  className="h-1 rounded-full bg-indigo-500 transition-all"
                  style={{ width: `${((onboardStep + 1) / totalOnboardSteps) * 100}%` }}
                />
              </div>
            </div>
            <button
              className="rounded-md border border-neutral-700 px-3 py-1 text-xs font-semibold text-neutral-200 hover:bg-neutral-900"
              onClick={() => closeOnboarding(true)}
            >
              Don’t show again
            </button>
          </div>

          <div className="space-y-2">
            {onboardSteps.map((step, index) => {
              const isActive = index === onboardStep
              const action = step.action
              return (
                <div
                  key={step.title}
                  className={`rounded-lg border px-3 py-2 ${
                    isActive
                      ? 'border-indigo-500/70 bg-indigo-500/10'
                      : 'border-neutral-800 bg-neutral-900/40'
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <span
                      className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold ${
                        isActive ? 'bg-indigo-500 text-white' : 'bg-neutral-800 text-neutral-200'
                      }`}
                    >
                      {index + 1}
                    </span>
                    <div className="space-y-1">
                      <div className="font-semibold text-neutral-100">{step.title}</div>
                      <div className="text-neutral-300">{step.description}</div>
                      <div className="text-xs text-neutral-400">{step.tip}</div>
                      {action && (
                        <button
                          className={`mt-1 rounded-md px-3 py-1.5 text-xs font-semibold ${
                            action.variant === 'primary'
                              ? 'bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-50'
                              : 'bg-neutral-800 text-neutral-100 hover:bg-neutral-700'
                          }`}
                          onClick={action.onClick}
                          disabled={action.disabled}
                        >
                          {action.label}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>

          <div className="flex items-center justify-between gap-2 pt-2">
            <button
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 px-3 py-2 text-sm font-semibold disabled:opacity-50"
              onClick={() => setOnboardStep((s) => Math.max(0, s - 1))}
              disabled={onboardStep === 0}
            >
              Back
            </button>
            <div className="flex gap-2">
              <button
                className="rounded-md bg-indigo-600 hover:bg-indigo-500 px-3 py-2 text-sm font-semibold"
                onClick={() => {
                  if (onboardStep >= 3) return closeOnboarding(true)
                  setOnboardStep((s) => Math.min(3, s + 1))
                }}
              >
                {onboardStep >= 3 ? 'Finish' : 'Next'}
              </button>
            </div>
          </div>
        </div>
      </Modal>
      
      {app.workspaceView === 'graph' && !app.focusGraph && !app.leftPanelOpen && (
        <button
          type="button"
          className="fixed left-2 top-1/2 -translate-y-1/2 z-[95] rounded-r-md bg-neutral-950/90 border border-neutral-700 px-1 py-2 text-xs font-semibold text-neutral-200 hover:bg-neutral-900 shadow-lg"
          onMouseDown={(e) => { e.preventDefault(); e.stopPropagation() }}
          onClick={() => app.toggleLeftPanel()}
          aria-label="Show left panel"
          title="Show left panel"
        >
          {'>'}
        </button>
      )}

      {app.workspaceView === 'graph' && !app.focusGraph && !app.rightPanelOpen && (
        <button
          type="button"
          className="fixed right-2 top-1/2 -translate-y-1/2 z-[95] rounded-l-md bg-neutral-950/90 border border-neutral-700 px-1 py-2 text-xs font-semibold text-neutral-200 hover:bg-neutral-900 shadow-lg"
          onMouseDown={(e) => { e.preventDefault(); e.stopPropagation() }}
          onClick={() => app.toggleRightPanel()}
          aria-label="Show right panel"
          title="Show right panel"
        >
          {'<'}
        </button>
      )}
    </div>
  )
}
