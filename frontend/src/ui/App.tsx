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
import { useCGRAPHApp } from './useCGRAPHApp'
import { CommandPalette } from './components/CommandPalette'
import { Modal } from './components/Modal'

export function App() {
  const app = useCGRAPHApp()

  const [docsOpen, setDocsOpen] = React.useState(false)
  const [onboardOpen, setOnboardOpen] = React.useState(false)
  const [onboardStep, setOnboardStep] = React.useState(0)
  const [editorExplorerOpen, setEditorExplorerOpen] = React.useState(true)

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
            />
          ) : (
            <div className="h-full w-full overflow-hidden flex relative">
              {app.workspaceView === 'editor' && editorExplorerOpen && (
                <div className="w-72 shrink-0 border-r border-neutral-800 bg-neutral-950/70 flex flex-col">
                  <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-neutral-800">
                    <div className="text-sm font-semibold text-neutral-200">Explorer</div>
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
                    <ExplorerTree
                      activeProject={app.activeProject}
                      busy={app.busy}
                      selectedPath={app.selectedPath}
                      onSelectPath={app.onSelectNodePath}
                      projectFiles={app.projectFiles}
                      projectFilesMeta={app.projectFilesMeta}
                      projectFilesBusy={app.projectFilesBusy}
                      showModuleSelect={false}
                    />
                  </div>
                </div>
              )}

              <div className="flex-1 min-w-0 h-full overflow-auto p-4">
                <FileEditorPane
                  open={app.fileEditorOpen}
                  path={app.fileEditorPath}
                  original={app.fileEditorOriginal}
                  content={app.fileEditorContent}
                  busy={app.fileEditorBusy}
                  saving={app.fileEditorSaving}
                  dirty={app.fileEditorDirty}
                  truncated={app.fileEditorTruncated}
                  error={app.fileEditorError}
                  onChange={app.setFileEditorContent}
                  onReload={app.reloadFileEditor}
                  onSave={app.saveFileEditor}
                  onClose={() => app.setWorkspaceView('graph')}
                />
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
            busy={app.busy}
            mode={app.mode}
            depth={app.depth}
            depMode={app.depMode}
            retrievalMode={app.retrievalMode}
            agenticMaxCalls={app.agenticMaxCalls}
            agenticMaxFileChars={app.agenticMaxFileChars}
            agenticMaxTotalToolOutputChars={app.agenticMaxTotalToolOutputChars}
            agenticTemperature={app.agenticTemperature}
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
      />

      <Modal
        open={app.confirmOpen}
        title="Несохранённые изменения"
        onClose={app.confirmCancel}
      >
        <div className="space-y-4">
          <div className="text-sm text-neutral-200">Есть несохранённые изменения.</div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 px-3 py-2 text-sm font-semibold disabled:opacity-50"
              onClick={() => void app.confirmCancel()}
              disabled={app.fileEditorSaving || app.fileEditorBusy}
            >
              Отмена
            </button>
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 px-3 py-2 text-sm font-semibold disabled:opacity-50"
              onClick={() => void app.confirmDiscard()}
              disabled={app.fileEditorSaving || app.fileEditorBusy}
            >
              Продолжить без сохранения
            </button>
            <button
              type="button"
              className="rounded-md bg-indigo-600 hover:bg-indigo-500 px-3 py-2 text-sm font-semibold disabled:opacity-50"
              onClick={() => void app.confirmSave()}
              disabled={app.fileEditorSaving || app.fileEditorBusy}
            >
              Сохранить
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
                Docs не обновились из-за ошибки — показана предыдущая версия.
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
          <div className="text-neutral-200">
            Step {onboardStep + 1}/4
          </div>
          {onboardStep === 0 && (
            <div className="space-y-2">
              <div>1) Проиндексируй проект: <span className="font-mono">Scan</span>.</div>
              <button
                className="rounded-md bg-indigo-600 hover:bg-indigo-500 px-3 py-2 text-sm font-semibold disabled:opacity-50"
                onClick={() => void app.onScan()}
                disabled={!app.activeProject || app.busy}
              >
                Scan now
              </button>
            </div>
          )}
          {onboardStep === 1 && (
            <div className="space-y-2">
              <div>2) Выбери файл: <span className="font-mono">Ctrl/⌘+K</span>, введи путь, Enter.</div>
              <button
                className="rounded-md bg-neutral-800 hover:bg-neutral-700 px-3 py-2 text-sm font-semibold"
                onClick={() => app.setPaletteOpen(true)}
              >
                Open palette
              </button>
            </div>
          )}
          {onboardStep === 2 && (
            <div className="space-y-2">
              <div>3) Клик по узлу — центрирование и подсветка связей.</div>
              <div>В focus-режиме (F) можно прятать/фиксировать узлы и сохранять раскладку.</div>
            </div>
          )}
          {onboardStep === 3 && (
            <div className="space-y-2">
              <div>4) Запусти задачу справа: выбери шаблон (chips) или напиши промпт и нажми Run.</div>
              <div className="text-[12px] text-neutral-400">История запусков — в “Recent runs” с фильтрами.</div>
            </div>
          )}

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
                className="rounded-md bg-neutral-900 hover:bg-neutral-800 px-3 py-2 text-sm font-semibold"
                onClick={() => closeOnboarding(true)}
              >
                Don’t show again
              </button>
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
