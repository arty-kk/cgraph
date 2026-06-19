import React from 'react'
import { ProjectsSidebar } from '@/features/projects'
import { GraphCanvas } from '@/features/graph'
import { NodePanel } from '@/features/analysis'
import { FileEditorPane } from '@/features/files'
import { ExplorerTree } from '@/features/files'
import type { useStubGraphApp } from './useStubGraphApp'

type Params = {
  app: ReturnType<typeof useStubGraphApp>
  gridTemplateColumns: string
  showDependencies: boolean
  editorWrap: boolean
  editorShowDiff: boolean
  editorExplorerOpen: boolean
  editorLeftTab: any
  editorFontSize: number
  editorTabs: any
  activeFileDependencies: any
  activeFileMeta: any
  activeSaveBanner: any
  activeFileDirty: boolean
  canQuickSummary: boolean
  quickSummaryDisabledReason?: string
  showEditorEmptyState: boolean
  totalIn: number
  totalOut: number
  searchInputRef: any
  handleFocusSearch: () => void
  handleSetFontSize: (n: number) => void
  openDocs: () => void
  setEditorExplorerOpen: React.Dispatch<React.SetStateAction<boolean>>
  setEditorLeftTab: React.Dispatch<React.SetStateAction<any>>
  setEditorShowDiff: React.Dispatch<React.SetStateAction<boolean>>
  setEditorWrap: React.Dispatch<React.SetStateAction<boolean>>
}

export function AppLayout({
  app, gridTemplateColumns, showDependencies, editorWrap, editorShowDiff, editorExplorerOpen, editorLeftTab,
  editorFontSize, editorTabs, activeFileDependencies, activeFileMeta, activeSaveBanner,
  activeFileDirty, canQuickSummary, quickSummaryDisabledReason, showEditorEmptyState,
  totalIn, totalOut, searchInputRef, handleFocusSearch, handleSetFontSize, openDocs,
  setEditorExplorerOpen, setEditorLeftTab, setEditorShowDiff, setEditorWrap,
}: Params) {
  return (
      <div className="h-full w-full min-h-0 overflow-x-hidden grid min-w-0" style={{ gridTemplateColumns, gridTemplateRows: '1fr' }}>

      {app.workspaceView === 'graph' && !app.focusGraph && app.leftPanelOpen && (
          <ProjectsSidebar
            onHidePanel={app.toggleLeftPanel}
            orgs={app.orgs}
            selectedOrgId={app.selectedOrgId}
            onSelectOrg={app.onSelectOrg}
            orgsLoading={app.orgsLoading}
            projects={app.projects}
            activeProject={app.activeProject}
            openFilePaths={app.openFilePaths}
            activeFilePath={app.activeFilePath}
            selectedPath={app.selectedPath}
            projectsLoading={app.projectsLoading}
            newName={app.newName}
            newArchive={app.newArchive}
            newPath={app.newPath}
            busy={app.busy}
            error={app.error}
            onPickProject={app.onPickProject}
            onCreateProject={app.onCreateProject}
            onDeleteActiveProject={app.onDeleteActiveProject}
            onScan={app.onScan}
            onRefresh={app.onRefresh}
            setNewName={app.setNewName}
            setNewArchive={app.setNewArchive}
            setNewPath={app.setNewPath}
            onCreateFile={app.onCreateFile}
            onRenameFile={app.onRenameFile}
            onDeleteFile={app.onDeleteFile}
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
            onRegisterFileMeta={app.registerFileMeta}
            pinnedPaths={app.pinnedPaths}
            allowLocalRootPath={app.allowLocalRootPath}
            onOpenDocs={openDocs}
          />
        )}

        <div className="min-w-0 min-h-0">
          {app.graphStale && (
            <div className="px-4 pt-3">
              <div className="rounded-md border border-amber-800/70 bg-amber-950/50 px-3 py-2 text-xs text-amber-100 flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="font-semibold">Graph may be stale</div>
                  <div className="text-[11px] text-amber-200">
                    {app.graphStaleMessage || 'Indexing is incomplete. Run a rescan to refresh the graph.'}
                  </div>
                </div>
                <button
                  type="button"
                  className="rounded-md border border-amber-800/70 bg-amber-900/40 px-2 py-1 text-[11px] font-semibold text-amber-100 hover:bg-amber-900/60 disabled:opacity-50"
                  onClick={() => void app.onScan()}
                  disabled={!app.activeProject || app.busy}
                >
                  Rescan now
                </button>
              </div>
            </div>
          )}
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
                    <div className="text-[11px] tracking-[0.25em] text-neutral-500">EXPLORER</div>
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
                  <div className="flex items-center gap-1 px-3 py-2 border-b border-neutral-800">
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
                        onRegisterFileMeta={app.registerFileMeta}
                        pinnedPaths={app.pinnedPaths}
                        showModuleSelect={false}
                        compact
                        showOpenEditors
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
                        <div className="text-sm font-semibold text-neutral-100">Edit faster</div>
                        <p className="text-xs text-neutral-400">
                          The graph shows structure and dependencies, while the editor is for precise code changes.
                          Open files with Ctrl/⌘+K and return to the graph with Ctrl/⌘+Shift+G.
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center justify-center gap-2">
                        <button
                          type="button"
                          className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2 text-xs font-semibold text-neutral-200 hover:bg-neutral-800"
                          onClick={() => app.setPaletteOpen(true)}
                        >
                          Open file (Ctrl/⌘+K)
                        </button>
                        <button
                          type="button"
                          className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2 text-xs font-semibold text-neutral-200 hover:bg-neutral-800"
                          onClick={handleFocusSearch}
                        >
                          Search project (Ctrl/⌘+Shift+F)
                        </button>
                        <button
                          type="button"
                          className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-2 text-xs font-semibold text-neutral-200 hover:bg-neutral-800"
                          onClick={() => app.setWorkspaceView('graph')}
                        >
                          Back to graph (Ctrl/⌘+Shift+G)
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
                      dependencyMeta={app.fileDependenciesMeta}
                      totalIn={totalIn}
                      totalOut={totalOut}
                      saveBanner={activeSaveBanner}
                      draftCount={app.draftCount}
                      onOpenDependencyInGraph={(path) => {
                        app.onSelectNodePath(path)
                        app.setWorkspaceView('graph')
                      }}
                      onOpenDependencyFile={(path) => {
                        app.setWorkspaceView('editor')
                        void Promise.resolve(app.openFileEditor(path))
                      }}
                      onLoadMoreDependencies={app.loadMoreDependencies}
                      onRescan={app.onScan}
                      onClearDrafts={app.clearDrafts}
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
          />
        )}
      </div>

  )
}
