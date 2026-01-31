// frontend/src/ui/components/ProjectsSidebar.tsx
import React from 'react'
import type { Project, ProjectFileItem, NodeSearchItem, SemanticSearchItem } from '../../api'
import { clampInt } from '../../lib/number'
import type { SemanticSearchErrorReason } from '../../lib/errors'
import { Modal } from './Modal'
import { LanguageIcon } from './LanguageIcon'
import { ExplorerTree } from './ExplorerTree'

type Props = {
  onHidePanel?: () => void
  projects: Project[]
  activeProject: Project | null
  openFilePaths: string[]
  activeFilePath: string | null
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
  onCreateFile: (path: string) => void | Promise<void>
  onRenameFile: (path: string, newPath: string) => void | Promise<void>
  onDeleteFile: (path: string) => void | Promise<void>

  projectFiles: ProjectFileItem[]
  projectFilesMeta: any
  projectFilesBusy: boolean
  pinnedPaths: string[]

  onOpenDocs: () => void | Promise<void>
}

export function ProjectsSidebar({
  onHidePanel,
  projects,
  activeProject,
  openFilePaths,
  activeFilePath,
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
  onCreateFile,
  onRenameFile,
  onDeleteFile,
  projectFiles,
  projectFilesMeta,
  projectFilesBusy,
  pinnedPaths,
  onOpenDocs,
}: Props) {
  const [helpOpen, setHelpOpen] = React.useState<null | 'projects' | 'graph' | 'search'>(null)
  const [confirmDeleteOpen, setConfirmDeleteOpen] = React.useState(false)

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

  const loadingCardBase = 'rounded-md border border-neutral-800 bg-neutral-950 px-3 py-2 text-xs text-neutral-400'
  const loadingCardPulse = `${loadingCardBase} animate-pulse`
  const searchResultRowClass = 'text-left text-xs bg-neutral-950 border border-neutral-800 rounded-md p-2 hover:border-neutral-700 disabled:opacity-50'
  const confirmDangerClass = 'h-9 rounded-md bg-red-700 hover:bg-red-600 px-3 text-sm font-semibold disabled:opacity-50'
  const confirmCancelClass = 'h-9 rounded-md bg-neutral-900 hover:bg-neutral-800 px-3 text-sm font-semibold disabled:opacity-50'
  const semanticUnavailableText = semanticSearchUnavailableReason === 'missing_api_key'
    ? 'OPENAI_API_KEY required'
    : semanticSearchUnavailableReason === 'embeddings_disabled'
      ? 'embeddings disabled'
      : semanticSearchUnavailableReason === 'no_embeddings'
        ? 'no embeddings'
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
      aria-label={label || 'Open help'}
      title={label || 'Help'}
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
          <div className="text-lg font-semibold">StubGraph</div>

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
              title="Show file tree and quick jump"
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
              title="Manage projects, graph, and search"
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
                      title="Open project docs (generated by backend)"
                    >
                      Docs
                    </button>
                  }
                />
              </div>

              <ExplorerTree
                activeProject={activeProject}
                busy={busy}
                openFilePaths={openFilePaths}
                activeFilePath={activeFilePath}
                selectedPath={selectedPath}
                onSelectPath={onSelectPath}
                onCreateFile={onCreateFile}
                onRenameFile={onRenameFile}
                onDeleteFile={onDeleteFile}
                projectFiles={projectFiles}
                projectFilesMeta={projectFilesMeta}
                projectFilesBusy={projectFilesBusy}
                pinnedPaths={pinnedPaths}
                showModuleSelect
              />
            </>
          )}

          {view === 'manage' && (
            <>

          {projectsLoading && projects.length === 0 ? (
            <div className={loadingCardPulse}>
              Loading project list…
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
                title="Select active project"
              >
                <option value="" disabled>
                  {projects.length ? 'Pick a project…' : 'No projects'}
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
                title="Delete active project (irreversible)"
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
            title="Project name (shown in the UI)"
          />
          <input
            className={inputSmClass}
            placeholder="/absolute/path/to/repo"
            value={newPath}
            onChange={(e) => setNewPath(e.target.value)}
            disabled={busy}
            title="Absolute path to the repository on the machine running the backend"
          />
          <div className="text-xs text-neutral-500 leading-relaxed">
            Path must be absolute
          </div>
          <button
            className={buttonPrimary}
            onClick={() => onCreateProject()}
            disabled={!newName.trim() || !newPath.trim() || busy}
            title="Create project and save root_path"
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
                title="local — neighborhood of the selected file; full — entire graph; top-N — limited graph of N nodes"
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
                title="Number of nodes for top-N mode"
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
                title="Dependency depth (hops) for graph building"
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
                title="Local graph size limit (for performance)"
              />
            </label>
          </div>

          <div className="mt-2 flex gap-2">
            <button
              className={buttonSoft}
              onClick={() => onScan()}
              disabled={!activeProject || busy}
              title="Scan: reindex project and recompute dependencies"
            >
              Scan
            </button>
            <button
              className={buttonNeutral}
              onClick={() => onRefresh()}
              disabled={!activeProject || busy}
              title="Refresh: reload graph and panel data"
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
          {semanticSearchUnavailableReason === 'no_embeddings' ? (
            <div className="mt-1 text-[11px] text-neutral-500">
              Enable embeddings and run Scan to restore search.
            </div>
          ) : null}
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
              title="Search by path substring via backend (Enter to search)"
            />
            <button
              className={buttonSoft}
              onClick={() => onSearchNodes(searchQuery)}
              disabled={!activeProject || busy || searchBusy || !searchQuery.trim()}
              title="Run search"
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
                  title="Select file (and open it in the right panel / local graph)"
                >
                  <div className="text-neutral-200 font-semibold">{r.path}</div>
                  <div className="text-neutral-500 inline-flex items-center gap-1">
                    <LanguageIcon language={r.language} className="h-3.5 w-3.5 text-neutral-400" />
                    <span>· In:{r.fan_in ?? 0} · Out:{r.fan_out ?? 0}</span>
                  </div>
                </button>
              ))}
            </div>
          )}

          {semanticSearchEnabled && semanticSearchFallbackUsed && searchResults.length > 0 && (
            <div className="mt-2 flex flex-col gap-1 max-h-40 overflow-auto">
              <div className="text-[11px] text-neutral-500">
                Showing fallback path search
              </div>
              {searchResults.map((r) => (
                <button
                  key={r.path}
                  className={searchResultRowClass}
                  onClick={() => onSelectPath(r.path)}
                  onMouseDown={(e) => e.preventDefault()}
                  disabled={!activeProject || busy}
                  title="Select file (and open it in the right panel / local graph)"
                >
                  <div className="text-neutral-200 font-semibold">{r.path}</div>
                  <div className="text-neutral-500 inline-flex items-center gap-1">
                    <LanguageIcon language={r.language} className="h-3.5 w-3.5 text-neutral-400" />
                    <span>· In:{r.fan_in ?? 0} · Out:{r.fan_out ?? 0}</span>
                  </div>
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
                    title="Select file (and open it in the right panel / local graph)"
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
              helpOpen === 'projects' ? 'Help: projects' : helpOpen === 'graph' ? 'Help: graph' : 'Help: search'
            }
            onClose={() => setHelpOpen(null)}
          >
            {helpOpen === 'projects' && (
              <div className="space-y-2">
                <div className="text-neutral-200 font-semibold">How projects work</div>
                <div>• Project is the repository root (<span className="font-mono">root_path</span>) on the machine running the backend.</div>
                <div>• Explorer shows the file tree (local filter by path substring).</div>
                <div>• Manage lets you select/create/delete projects, manage the graph, and search files via the backend.</div>
                <div>• Delete removes the project and all related data (graph, contracts, run history). This is irreversible.</div>
              </div>
            )}
            {helpOpen === 'graph' && (
              <div className="space-y-2">
                <div className="text-neutral-200 font-semibold">Graph settings</div>
                <div>• Mode:</div>
                <div className="ml-3">— <span className="font-mono">Local</span>: neighborhood of the selected file (requires a selected file).</div>
                <div className="ml-3">— <span className="font-mono">Full</span>: entire project graph.</div>
                <div className="ml-3">— <span className="font-mono">Top-N</span>: limited graph of <span className="font-mono">N</span> nodes (by backend scoring).</div>
                <div>• N is used only for <span className="font-mono">Top-N</span> mode.</div>
                <div>• Hops — dependency depth (number of steps along edges).</div>
                <div>• Max Nodes (Local) — local graph size limit for speed/readability.</div>
                <div className="pt-2">• <span className="font-mono">Scan</span> — reindex and recompute dependencies.</div>
                <div>• <span className="font-mono">Refresh</span> — reload graph/panel data without changing settings.</div>
              </div>
            )}
            {helpOpen === 'search' && (
              <div className="space-y-2">
                <div className="text-neutral-200 font-semibold">Search and filtering</div>
                <div>• Manage → “Search file” — backend query by path substring (e.g. <span className="font-mono">service/</span>).</div>
                <div>• Explorer → “Filter (Path)…” — local file tree filter (no requests).</div>
                <div>• Clicking a result selects the file; for <span className="font-mono">local</span> mode this is required.</div>
              </div>
            )}
          </Modal>

          <Modal open={confirmDeleteOpen} title="Delete project?" onClose={() => setConfirmDeleteOpen(false)}>
            <div className="space-y-3">
              <div className="text-sm text-neutral-200">
                This will delete: graph, nodes/edges, contracts, and run history for this project.
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  className={confirmDangerClass}
                  onClick={async () => {
                    setConfirmDeleteOpen(false)
                    await onDeleteActiveProject()
                  }}
                  title="Confirm delete"
                >
                  Yes, delete
                </button>
                <button
                  type="button"
                  className={confirmCancelClass}
                  onClick={() => setConfirmDeleteOpen(false)}
                  title="Cancel"
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
