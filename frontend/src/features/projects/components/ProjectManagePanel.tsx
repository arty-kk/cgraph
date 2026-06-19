import React from 'react'
import type { Org, Project, NodeSearchItem, SemanticSearchItem } from '@/api'
import type { SemanticSearchErrorReason } from '@/shared/lib/errors'
import { clampInt } from '@/shared/lib/number'
import { LanguageIcon } from '@/shared/ui/LanguageIcon'
import { SectionHeader, type HelpTopic } from './SectionHeader'
import type { Props as SidebarProps } from './ProjectsSidebar'
import {
  buttonDanger, buttonNeutral, buttonPrimary, buttonSoft, controlClass, fieldLabelClass,
  inputSmClass, inputSmFlexClass, labelRowClass, loadingCardPulse, searchResultRowClass, selectSmFlexClass,
} from '../lib/projectsSidebar.styles'

type Params = SidebarProps & {
  canEditProjects: boolean
  canDeleteProject: boolean
  localRootDisabled: boolean
  semanticUnavailableText: React.ReactNode
  setConfirmDeleteOpen: (v: boolean) => void
  onOpenHelp: (t: HelpTopic) => void
}

export function ProjectManagePanel({
  activeProject,
  busy,
  canDeleteProject,
  canEditProjects,
  error,
  graphHops,
  graphLimitN,
  graphLocalMax,
  graphMode,
  localRootDisabled,
  newArchive,
  newName,
  newPath,
  onCreateProject,
  onPickProject,
  onRefresh,
  onScan,
  onSearchNodes,
  onSelectOrg,
  onSelectPath,
  orgs,
  orgsLoading,
  projects,
  projectsLoading,
  searchBusy,
  searchQuery,
  searchResults,
  searchSemanticResults,
  selectedOrgId,
  semanticSearchEnabled,
  semanticSearchFallbackUsed,
  semanticSearchUnavailableReason,
  semanticUnavailableText,
  setConfirmDeleteOpen,
  setGraphHops,
  setGraphLimitN,
  setGraphLocalMax,
  setGraphMode,
  setNewArchive,
  setNewName,
  setNewPath,
  setSearchQuery,
  setSemanticSearchEnabled,
  onOpenHelp,
}: Params) {
  return (
    <>
            <>
              <div className="mt-2">
                <div className={labelRowClass}>
                  <div className={fieldLabelClass}>Organization</div>
                </div>
              </div>

              {orgsLoading && orgs.length === 0 ? (
                <div className={loadingCardPulse}>
                  Loading organizations…
                </div>
              ) : orgs.length === 1 ? (
                <div className="text-xs text-neutral-300 truncate" title={orgs[0]?.name ?? ''}>
                  {orgs[0]?.name ?? 'Unknown organization'}
                </div>
              ) : (
                <div className="flex gap-2 w-full">
                  <select
                    className={selectSmFlexClass}
                    value={selectedOrgId ?? ''}
                    disabled={busy || orgs.length === 0}
                    onChange={(e) => {
                      const id = Number(e.target.value)
                      const org = orgs.find((x) => x.id === id)
                      onSelectOrg(org ? org.id : null)
                    }}
                    title="Select organization"
                  >
                    <option value="" disabled>
                      {orgs.length ? 'Pick an organization…' : 'No organizations'}
                    </option>
                    {orgs.map((org) => (
                      <option key={org.id} value={org.id}>
                        {org.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}

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
                    disabled={!activeProject || busy || !canDeleteProject}
                    onClick={() => setConfirmDeleteOpen(true)}
                    title={
                      canDeleteProject
                        ? 'Delete active project (irreversible)'
                        : 'Only org admins can delete projects'
                    }
                  >
                    Delete
                  </button>
                </div>
              )}

          {activeProject && (
            <div
              className="text-xs text-neutral-400 truncate"
              title={activeProject.source?.label ?? activeProject.root_path ?? ''}
            >
              {activeProject.source?.label ?? activeProject.root_path}
            </div>
          )}

          <div className="mt-3 text-sm font-semibold text-neutral-200">Add</div>
          {!canEditProjects && (
            <div className="text-xs text-neutral-500 leading-relaxed">
              Only org members can create projects.
            </div>
          )}
          <input
            className={inputSmClass}
            placeholder="name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            disabled={busy || !canEditProjects}
            title="Project name (shown in the UI)"
          />
          <input
            className={inputSmClass}
            type="file"
            accept=".zip,.tar,.tar.gz,.tgz"
            onChange={(e) => setNewArchive(e.target.files?.[0] ?? null)}
            disabled={busy || !canEditProjects}
            title="Upload repository snapshot (.zip/.tar/.tar.gz/.tgz)"
          />
          <div className="text-xs text-neutral-500 leading-relaxed">
            Upload snapshot archive (zip/tar).
          </div>
          {newArchive && (
            <div className="text-xs text-neutral-500 truncate" title={newArchive.name}>
              Selected: {newArchive.name}
            </div>
          )}
          <input
            className={inputSmClass}
            placeholder="/absolute/path/to/repo"
            value={newPath}
            onChange={(e) => setNewPath(e.target.value)}
            disabled={busy || Boolean(newArchive) || localRootDisabled || !canEditProjects}
            title="Absolute path on the backend machine (local-only)"
          />
          <div className="text-xs text-neutral-500 leading-relaxed">
            {localRootDisabled ? 'Local root_path is disabled on this server.' : 'Local root_path works only when enabled on the backend.'}
          </div>
          <button
            className={buttonPrimary}
            onClick={() => onCreateProject()}
            disabled={
              !newName.trim() ||
              (!newArchive && (!newPath.trim() || localRootDisabled)) ||
              busy ||
              !canEditProjects
            }
            title={
              canEditProjects
                ? 'Create project from snapshot or local root_path'
                : 'Creating projects requires the member role'
            }
          >
            Create Project
          </button>

          <div className="mt-4">
            <SectionHeader onOpenHelp={onOpenHelp} title="Graph" topic="graph" />
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
              disabled={!activeProject || busy || !canEditProjects}
              title={
                canEditProjects
                  ? 'Scan: reindex project and recompute dependencies'
                  : 'Scanning requires the member role'
              }
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
            <SectionHeader onOpenHelp={onOpenHelp} title="File Search" topic="search" />
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
    </>
  )
}
