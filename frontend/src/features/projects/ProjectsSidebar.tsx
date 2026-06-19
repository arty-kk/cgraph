// frontend/src/ui/components/ProjectsSidebar.tsx
import React from 'react'
import type { Org, Project, ProjectTreeEntry, NodeSearchItem, SemanticSearchItem } from '@/api'
import { roleAtLeast } from '@/shared/lib/roles'
import { safeStorageGet, safeStorageSet } from '@/shared/lib/storage'
import type { SemanticSearchErrorReason } from '@/shared/lib/errors'
import { Modal } from '@/shared/ui/Modal'
import { ExplorerTree } from '@/features/files/ExplorerTree'
import { ProjectManagePanel } from './ProjectManagePanel'
import { SectionHeader } from './SectionHeader'
import { tabBase, tabActive, tabIdle, miniButtonClass, confirmDangerClass, confirmCancelClass } from './projectsSidebar.styles'

export type Props = {
  onHidePanel?: () => void
  orgs: Org[]
  selectedOrgId: number | null
  onSelectOrg: (id: number | null) => void | Promise<void>
  orgsLoading: boolean
  projects: Project[]
  activeProject: Project | null
  openFilePaths: string[]
  activeFilePath: string | null
  selectedPath: string | null
  projectsLoading: boolean
  newName: string
  newArchive: File | null
  newPath: string
  busy: boolean
  error: string | null

  setNewName: (v: string) => void
  setNewArchive: (v: File | null) => void
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

  onRegisterFileMeta?: (entries: ProjectTreeEntry[]) => void
  pinnedPaths: string[]
  allowLocalRootPath: boolean | null

  onOpenDocs: () => void | Promise<void>
}

export function ProjectsSidebar(props: Props) {
  const {
  onHidePanel,
  orgs,
  selectedOrgId,
  onSelectOrg,
  orgsLoading,
  projects,
  activeProject,
  openFilePaths,
  activeFilePath,
  selectedPath,
  projectsLoading,
  newName,
  newArchive,
  newPath,
  busy,
  error,
  setNewName,
  setNewArchive,
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
  onRegisterFileMeta,
  pinnedPaths,
  allowLocalRootPath,
  onOpenDocs,
  } = props
  const [helpOpen, setHelpOpen] = React.useState<null | 'projects' | 'graph' | 'search'>(null)
  const [confirmDeleteOpen, setConfirmDeleteOpen] = React.useState(false)

  // Deleting a project requires the admin role server-side. Surface that as a
  // disabled, explained affordance. When the role is unknown (older backend or
  // initial load) keep the prior behaviour and let the server enforce.
  const activeOrg = React.useMemo(
    () => orgs.find((o) => o.id === selectedOrgId) ?? (orgs.length === 1 ? orgs[0] : undefined),
    [orgs, selectedOrgId],
  )
  const canDeleteProject = activeOrg?.role == null || roleAtLeast(activeOrg.role, 'admin')
  // Mutating project actions (create / import / scan) require at least the
  // member role server-side; mirror that so viewers aren't shown actions that
  // only 403 on click. Unknown role keeps prior behaviour (server enforces).
  const canEditProjects = activeOrg?.role == null || roleAtLeast(activeOrg.role, 'member')

  const semanticUnavailableText = semanticSearchUnavailableReason === 'missing_api_key'
    ? 'OPENAI_API_KEY required'
    : semanticSearchUnavailableReason === 'embeddings_disabled'
      ? 'embeddings disabled'
      : semanticSearchUnavailableReason === 'no_embeddings'
        ? 'no embeddings'
      : ''
  const localRootDisabled = allowLocalRootPath === false



  type View = 'explorer' | 'manage'
  const [view, setView] = React.useState<View>(() => {
    const v = (safeStorageGet('cs.ui.sidebarView', '') || '').trim()
    return v === 'manage' ? 'manage' : 'explorer'
  })
  React.useEffect(() => {
    safeStorageSet('cs.ui.sidebarView', view)
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
            <SectionHeader onOpenHelp={setHelpOpen} title="Project" topic="projects" />
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
                <SectionHeader onOpenHelp={setHelpOpen}
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
                onRegisterFileMeta={onRegisterFileMeta}
                pinnedPaths={pinnedPaths}
                showModuleSelect
              />
            </>
          )}

      {view === 'manage' && (
        <ProjectManagePanel
          {...props}
          canEditProjects={canEditProjects}
          canDeleteProject={canDeleteProject}
          localRootDisabled={localRootDisabled}
          semanticUnavailableText={semanticUnavailableText}
          setConfirmDeleteOpen={setConfirmDeleteOpen}
          onOpenHelp={setHelpOpen}
        />
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
                <div>• Project is created from a repository snapshot (zip/tar) or a local root_path (dev only).</div>
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
