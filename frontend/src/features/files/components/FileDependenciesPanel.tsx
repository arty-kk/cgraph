import React from 'react'

type Props = {
  path: string | null
  depsIn: string[]
  depsOut: string[]
  totalInCount: number
  totalOutCount: number
  depButtonClass: string
  depsCanLoadMore: boolean
  depsTruncated: boolean
  DEP_LIMIT: number
  dependencyMeta?: {
    truncated_in?: boolean
    truncated_out?: boolean
    next_cursor_in?: string | null
    next_cursor_out?: string | null
  } | null
  depsOpen: boolean
  setDepsOpen: React.Dispatch<React.SetStateAction<boolean>>
  onOpenDependencyInGraph: (path: string) => void
  onOpenDependencyFile: (path: string) => void
  onLoadMoreDependencies?: () => void
}

/** Inbound/outbound file dependencies panel (collapsible, paged). Extracted verbatim from FileEditorPane. */
export function FileDependenciesPanel({
  path,
  depsIn,
  depsOut,
  totalInCount,
  totalOutCount,
  depButtonClass,
  depsCanLoadMore,
  depsTruncated,
  DEP_LIMIT,
  dependencyMeta,
  depsOpen,
  setDepsOpen,
  onOpenDependencyInGraph,
  onOpenDependencyFile,
  onLoadMoreDependencies,
}: Props) {
  return (
        <div className="rounded-md border border-neutral-800 bg-neutral-950/80 px-3 py-2 text-[11px] text-neutral-300">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] uppercase tracking-[0.2em] text-neutral-500">Dependencies</span>
              <span className="text-[10px] text-neutral-500">In {totalInCount} · Out {totalOutCount}</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className={depButtonClass}
                onClick={() => setDepsOpen((prev) => !prev)}
                aria-expanded={depsOpen}
              >
                {depsOpen ? 'Hide list' : 'Show list'}
              </button>
              <button
                type="button"
                className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
                onClick={() => path && onOpenDependencyInGraph(path)}
                disabled={!path}
              >
                Open in graph
              </button>
            </div>
          </div>
          {depsTruncated && (
            <div className="mt-2 rounded-md border border-amber-800/60 bg-amber-950/40 px-2 py-1 text-[10px] text-amber-200">
              <div>Partial results — the dependency list is truncated.</div>
              <div className="mt-1 flex flex-wrap gap-2">
                <button
                  type="button"
                  className={depButtonClass}
                  onClick={() => onLoadMoreDependencies?.()}
                  disabled={!depsCanLoadMore || !onLoadMoreDependencies}
                >
                  Load more
                </button>
                <button
                  type="button"
                  className={depButtonClass}
                  onClick={() => path && onOpenDependencyInGraph(path)}
                  disabled={!path}
                >
                  Open in graph
                </button>
              </div>
            </div>
          )}
          {depsOpen && (
            <div className="mt-2 grid gap-3 sm:grid-cols-2">
              <div className="space-y-2">
                <div className="flex items-center justify-between text-[10px] text-neutral-500">
                  <span className="uppercase tracking-[0.2em]">In</span>
                  <span className="text-neutral-400">{totalInCount}</span>
                </div>
                <div className="space-y-1">
                  {depsIn.slice(0, DEP_LIMIT).map((depPath) => (
                    <div key={`dep-in-${depPath}`} className="flex items-center justify-between gap-2">
                      <span className="min-w-0 flex-1 truncate text-[11px] text-neutral-200" title={depPath}>
                        {depPath}
                      </span>
                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          type="button"
                          className={depButtonClass}
                          onClick={() => onOpenDependencyInGraph(depPath)}
                        >
                          Open in graph
                        </button>
                        <button
                          type="button"
                          className={depButtonClass}
                          onClick={() => onOpenDependencyFile(depPath)}
                        >
                          Open file
                        </button>
                      </div>
                    </div>
                  ))}
                  {!depsIn.length && <div className="text-[11px] text-neutral-500">—</div>}
                </div>
                {(depsIn.length > DEP_LIMIT || dependencyMeta?.truncated_in) && (
                  <button
                    type="button"
                    className={depButtonClass}
                    onClick={() => path && onOpenDependencyInGraph(path)}
                    disabled={!path}
                  >
                    Show more…
                  </button>
                )}
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between text-[10px] text-neutral-500">
                  <span className="uppercase tracking-[0.2em]">Out</span>
                  <span className="text-neutral-400">{totalOutCount}</span>
                </div>
                <div className="space-y-1">
                  {depsOut.slice(0, DEP_LIMIT).map((depPath) => (
                    <div key={`dep-out-${depPath}`} className="flex items-center justify-between gap-2">
                      <span className="min-w-0 flex-1 truncate text-[11px] text-neutral-200" title={depPath}>
                        {depPath}
                      </span>
                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          type="button"
                          className={depButtonClass}
                          onClick={() => onOpenDependencyInGraph(depPath)}
                        >
                          Open in graph
                        </button>
                        <button
                          type="button"
                          className={depButtonClass}
                          onClick={() => onOpenDependencyFile(depPath)}
                        >
                          Open file
                        </button>
                      </div>
                    </div>
                  ))}
                  {!depsOut.length && <div className="text-[11px] text-neutral-500">—</div>}
                </div>
                {(depsOut.length > DEP_LIMIT || dependencyMeta?.truncated_out) && (
                  <button
                    type="button"
                    className={depButtonClass}
                    onClick={() => path && onOpenDependencyInGraph(path)}
                    disabled={!path}
                  >
                    Show more…
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
  )
}
