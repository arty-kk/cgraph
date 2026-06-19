// frontend/src/ui/App.tsx
import React from 'react'
import { Notifications } from './Notifications'
import { useStubGraphApp } from './useStubGraphApp'
import { AppLayout } from './AppLayout'
import { AppModals } from './AppModals'
import { CommandPalette } from '@/features/command-palette'
import { addStorageErrorListener, safeStorageGet, safeStorageSet } from '@/shared/lib/storage'

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
    const raw = safeStorageGet('cs.editor.explorerOpen')
    if (raw === '0') return false
    if (raw === '1') return true
    return true
  })
  const [editorLeftTab, setEditorLeftTab] = React.useState<'explorer' | 'search'>(() => {
    const raw = safeStorageGet('cs.editor.leftTab')
    return raw === 'explorer' || raw === 'search' ? raw : 'explorer'
  })
  const [editorWrap, setEditorWrap] = React.useState(() => {
    return (safeStorageGet('cs.editor.wrap', '1') || '1') !== '0'
  })
  const [editorShowDiff, setEditorShowDiff] = React.useState(() => {
    return (safeStorageGet('cs.editor.showDiff', '') || '') === '1'
  })
  const [editorFontSize, setEditorFontSize] = React.useState(() => {
    const raw = safeStorageGet('cs.editor.fontSize')
    const parsed = raw ? Number(raw) : Number.NaN
    return Number.isFinite(parsed) ? parsed : 13
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
    const seen = safeStorageGet(onboardKey) === '1'
    if (!seen) { setOnboardOpen(true); setOnboardStep(0) }
  }, [pid, onboardKey])

  const closeOnboarding = (markSeen: boolean) => {
    if (markSeen && onboardKey) {
      safeStorageSet(onboardKey, '1')
    }
    setOnboardOpen(false)
  }

  const filePathSet = React.useMemo(() => {
    const s = new Set<string>()
    const entries = app.fileMetaByPath || {}
    Object.keys(entries).forEach((p) => {
      if (p) s.add(p)
    })
    return s
  }, [app.fileMetaByPath])

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
    return app.fileMetaByPath?.[app.activeFilePath] ?? null
  }, [app.activeFilePath, app.fileMetaByPath])

  const activeFileDependencies = app.fileDependencies ?? { in: [], out: [] }
  const totalIn = app.fileDependenciesMeta?.total_in ?? activeFileDependencies.in.length
  const totalOut = app.fileDependenciesMeta?.total_out ?? activeFileDependencies.out.length
  const activeSaveBanner =
    app.fileSaveBanner && app.activeFilePath && app.fileSaveBanner.path === app.activeFilePath
      ? app.fileSaveBanner
      : null

  const confirmTitle = app.confirmReason === 'reload-file' ? 'Reload file?' : 'Unsaved changes'
  const confirmBody =
    app.confirmReason === 'reload-file'
      ? 'Reloading the file will discard unsaved changes.'
      : 'You have unsaved changes.'

  const clampFontSize = React.useCallback((value: number) => Math.min(16, Math.max(12, value)), [])

  const taskStatuses = app.taskStatuses ?? []
  const hasTaskStatuses = taskStatuses.length > 0

  React.useEffect(() => {
    setEditorFontSize((prev) => clampFontSize(prev))
  }, [clampFontSize])

  React.useEffect(() => {
    safeStorageSet('cs.editor.wrap', editorWrap ? '1' : '0')
  }, [editorWrap])

  React.useEffect(() => {
    safeStorageSet('cs.editor.explorerOpen', editorExplorerOpen ? '1' : '0')
  }, [editorExplorerOpen])

  React.useEffect(() => {
    safeStorageSet('cs.editor.leftTab', editorLeftTab)
  }, [editorLeftTab])

  React.useEffect(() => {
    safeStorageSet('cs.editor.showDiff', editorShowDiff ? '1' : '0')
  }, [editorShowDiff])

  React.useEffect(() => {
    safeStorageSet('cs.editor.fontSize', String(editorFontSize))
  }, [editorFontSize])

  React.useEffect(() => {
    return addStorageErrorListener(() => {
      app.notifyInfo('Local storage unavailable — settings will not be saved.')
    })
  }, [app])

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

  const onboardSteps = [
    {
      title: 'Scan the project',
      description: 'Index the project so the graph can build relationships.',
      tip: 'Scan — left toolbar.',
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
      title: 'Open the editor',
      description: 'The editor is the workspace for search, diff, outline, and quick jumps to the graph.',
      tip: 'Switch views — Ctrl/⌘+Shift+G.',
      action: {
        label: 'Open editor',
        onClick: () => app.setWorkspaceView('editor'),
        disabled: false,
        variant: 'secondary',
      },
    },
    {
      title: 'Explore the graph',
      description: 'Click a node to center it and highlight its edges.',
      tip: 'Graph — center view.',
    },
    {
      title: 'Run a task',
      description: 'Pick a chip or write a prompt, then press Run.',
      tip: 'Tasks — right panel.',
    },
  ]
  const totalOnboardSteps = onboardSteps.length

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
      {hasTaskStatuses && (
        <div className="absolute top-3 left-1/2 -translate-x-1/2 z-[120] w-[min(780px,92vw)]">
          <div className="rounded-md border border-neutral-800 bg-neutral-950/95 px-3 py-2 text-xs shadow-lg">
            <div className="flex items-center justify-between gap-3">
              <div className="font-semibold text-neutral-200">Background tasks</div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[10px] font-semibold text-neutral-200 hover:bg-neutral-800"
                  onClick={() => void app.refreshTaskStatuses()}
                >
                  Refresh
                </button>
                <button
                  type="button"
                  className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[10px] font-semibold text-neutral-200 hover:bg-neutral-800"
                  onClick={() => app.clearFinishedTasks()}
                >
                  Clear completed
                </button>
              </div>
            </div>
            <div className="mt-2 flex flex-col gap-1">
              {taskStatuses.map((task) => (
                <div key={task.id} className="flex items-center justify-between gap-2 text-[11px]">
                  <div className="min-w-0 flex items-center gap-2">
                    <span className="truncate text-neutral-200">{task.label}</span>
                    <span className="text-neutral-500">· {task.kind}</span>
                  </div>
                  <div className="flex items-center gap-2 text-neutral-400">
                    <span className="uppercase">{task.status}</span>
                    {task.error && <span className="text-rose-300">· {task.error}</span>}
                    <button
                      type="button"
                      className="rounded-md border border-neutral-800 bg-neutral-900 px-1.5 py-0.5 text-[10px] font-semibold text-neutral-200 hover:bg-neutral-800"
                      onClick={() => app.dismissTaskStatus(task.id)}
                    >
                      Dismiss
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
      <AppLayout
        app={app}
        gridTemplateColumns={gridTemplateColumns}
        showDependencies={showDependencies}
        editorWrap={editorWrap}
        editorShowDiff={editorShowDiff}
        editorExplorerOpen={editorExplorerOpen}
        editorLeftTab={editorLeftTab}
        editorFontSize={editorFontSize}
        editorTabs={editorTabs}
        activeFileDependencies={activeFileDependencies}
        activeFileMeta={activeFileMeta}
        activeSaveBanner={activeSaveBanner}
        activeFileDirty={activeFileDirty}
        canQuickSummary={canQuickSummary}
        quickSummaryDisabledReason={quickSummaryDisabledReason}
        showEditorEmptyState={showEditorEmptyState}
        totalIn={totalIn}
        totalOut={totalOut}
        searchInputRef={searchInputRef}
        handleFocusSearch={handleFocusSearch}
        handleSetFontSize={handleSetFontSize}
        openDocs={openDocs}
        setEditorExplorerOpen={setEditorExplorerOpen}
        setEditorLeftTab={setEditorLeftTab}
        setEditorShowDiff={setEditorShowDiff}
        setEditorWrap={setEditorWrap}
      />

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

      <AppModals
        app={app}
        docsOpen={docsOpen}
        setDocsOpen={setDocsOpen}
        onboardOpen={onboardOpen}
        closeOnboarding={closeOnboarding}
        onboardStep={onboardStep}
        setOnboardStep={setOnboardStep}
        onboardSteps={onboardSteps}
        totalOnboardSteps={totalOnboardSteps}
        confirmTitle={confirmTitle}
        confirmBody={confirmBody}
        filePathSet={filePathSet}
      />
      
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
