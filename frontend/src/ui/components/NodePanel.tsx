// frontend/src/ui/components/NodePanel.tsx
import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { DepMode, Mode, Project, RunRecord } from '../../api'
import { clampInt } from '../../lib/number'
import { formatResult } from '../../lib/formatResult'

type AutoOrMode = 'auto' | Mode

type Props = {
  activeProject: Project | null
  selectedPath: string | null
  selectedInGraph: boolean
  graphTruncated: boolean
  onLoadFullGraph: () => void | Promise<void>

  nodeBusy: boolean
  nodeInfo: any | null
  contract: any | null

  busy: boolean
  mode: AutoOrMode
  depth: number
  depMode: DepMode
  applyPatch: boolean
  prompt: string

  setMode: (v: AutoOrMode) => void
  setDepth: (v: number) => void
  setDepMode: (v: DepMode) => void
  setApplyPatch: (v: boolean) => void
  setPrompt: (v: string) => void

  canRun: boolean
  onRun: () => void | Promise<void>

  runResult: any | null
  fullPatch: string | null
  patchBusy: boolean
  runLoadBusy: boolean
  onLoadFullPatch: () => void | Promise<void>
  onLoadRun: (runId: number) => void | Promise<void>
  runs: RunRecord[]
}

export function NodePanel({
  activeProject,
  selectedPath,
  selectedInGraph,
  graphTruncated,
  onLoadFullGraph,
  nodeBusy,
  nodeInfo,
  contract,
  busy,
  mode,
  depth,
  depMode,
  applyPatch,
  prompt,
  setMode,
  setDepth,
  setDepMode,
  setApplyPatch,
  setPrompt,
  canRun,
  onRun,
  runResult,
  fullPatch,
  patchBusy,
  runLoadBusy,
  onLoadFullPatch,
  onLoadRun,
  runs,
}: Props) {

  const isAuto = mode === 'auto'
  const patchAllowed = isAuto || mode === 'fix'

  return (
    <div className="border-l border-neutral-800 p-4 overflow-auto">
      {!selectedPath ? (
        <div className="text-sm text-neutral-300">Кликни на узел (файл) в графе.</div>
      ) : (
        <>
          <div className="text-sm font-semibold">{selectedPath}</div>

          {!selectedInGraph && graphTruncated && (
            <div className="mt-2 text-xs bg-neutral-950 border border-neutral-800 rounded-md p-2">
              <div className="text-neutral-300">
                Этот файл не попал в текущий граф (graph limited / top-N). Это не ошибка файла.
              </div>
              <button
                className="mt-2 rounded-md bg-neutral-800 hover:bg-neutral-700 px-3 py-2 text-xs font-semibold disabled:opacity-50"
                onClick={() => onLoadFullGraph()}
                disabled={!activeProject}
                title="Load full graph"
              >
                Load full graph
              </button>
            </div>
          )}

          {!nodeBusy && selectedPath && !selectedInGraph && (
            <div className="mt-2 text-xs text-amber-300 whitespace-pre-wrap">
              Файл отсутствует в графе (возможно удалён/переименован или ещё не проиндексирован).
              {'\n'}
              Нажми Scan или Refresh.
            </div>
          )}

          {nodeBusy ? (
            <div className="mt-2 text-xs text-neutral-400">Loading node…</div>
          ) : (
            nodeInfo && (
              <div className="mt-2 text-xs text-neutral-300 grid grid-cols-2 gap-2">
                <div>
                  lang: <span className="text-neutral-100">{nodeInfo.language}</span>
                </div>
                <div>
                  loc: <span className="text-neutral-100">{nodeInfo.loc}</span>
                </div>
                <div>
                  fan_in: <span className="text-neutral-100">{nodeInfo.fan_in}</span>
                </div>
                <div>
                  fan_out: <span className="text-neutral-100">{nodeInfo.fan_out}</span>
                </div>
                <div>
                  complexity: <span className="text-neutral-100">{nodeInfo.complexity}</span>
                </div>
                <div>
                  scc: <span className="text-neutral-100">{nodeInfo.scc_id}</span>
                </div>
              </div>
            )
          )}

          <div className="mt-3">
            <div className="text-xs font-semibold text-neutral-200">Contract</div>
            <pre className="mt-1 text-xs bg-neutral-900 border border-neutral-800 rounded-md p-2 overflow-auto max-h-40">
              {nodeBusy ? 'Loading…' : contract ? JSON.stringify(contract, null, 2) : '—'}
            </pre>
          </div>

          <div className="mt-3">
            <div className="text-xs font-semibold text-neutral-200">Run task</div>

            <div className="mt-2 grid grid-cols-2 gap-2">
              <label className="text-xs text-neutral-300">
                Mode
                <select
                  className="mt-1 w-full rounded-md bg-neutral-900 border border-neutral-800 px-2 py-1 text-xs"
                  value={mode}
                  onChange={(e) => setMode(e.target.value as AutoOrMode)}
                  disabled={busy}
                >
                  <option value="auto">auto</option>
                  <option value="analyze">analyze</option>
                  <option value="evolve">evolve</option>
                  <option value="fix">fix</option>
                  <option value="impact">impact</option>
                </select>
              </label>

              <label className="text-xs text-neutral-300">
                Depth
                <input
                  type="number"
                  className="mt-1 w-full rounded-md bg-neutral-900 border border-neutral-800 px-2 py-1 text-xs"
                  value={depth}
                  min={0}
                  max={6}
                  onChange={(e) => {
                    const raw = e.target.value
                    const next = raw === '' ? 1 : clampInt(Number(raw), 0, 6)
                    setDepth(next)
                  }}
                  disabled={busy || isAuto}
                />
              </label>

              <label className="text-xs text-neutral-300">
                Deps
                <select
                  className="mt-1 w-full rounded-md bg-neutral-900 border border-neutral-800 px-2 py-1 text-xs"
                  value={depMode}
                  onChange={(e) => setDepMode(e.target.value as DepMode)}
                  disabled={busy || isAuto}
                >
                  <option value="contracts">contracts</option>
                  <option value="full">full</option>
                </select>
              </label>

              <label className="text-xs text-neutral-300 flex items-end gap-2">
                <input
                  type="checkbox"
                  checked={applyPatch}
                  onChange={(e) => setApplyPatch(e.target.checked)}
                  disabled={busy || !patchAllowed}
                />
                Apply patch
              </label>
            </div>

            <textarea
              className="mt-2 w-full rounded-md bg-neutral-900 border border-neutral-800 px-3 py-2 text-xs min-h-[90px]"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              disabled={busy}
            />

            <button
              className="mt-2 w-full rounded-md bg-indigo-600 hover:bg-indigo-500 px-3 py-2 text-sm font-semibold disabled:opacity-50"
              onClick={() => onRun()}
              disabled={!canRun}
            >
              {busy ? 'Running...' : 'Run'}
            </button>

            {!activeProject && <div className="mt-2 text-xs text-neutral-500">Выбери проект.</div>}
            {activeProject && !selectedPath && <div className="mt-2 text-xs text-neutral-500">Выбери файл в графе.</div>}
          </div>

          <div className="mt-4">
            <div className="text-xs font-semibold text-neutral-200">Result</div>
            {!runResult ? (
              <div className="mt-2 text-xs text-neutral-400">—</div>
            ) : (
              <div className="mt-2 space-y-3">
                <div className="text-xs text-neutral-400">
                  run_id: {runResult?.run_id ?? '—'} · mode: {runResult?.mode ?? '—'} · depth:{' '}
                  {runResult?.depth ?? '—'} · dep_mode: {runResult?.dep_mode ?? '—'}
                </div>

                {runResult?.applied?.error && (
                  <div className="text-xs text-red-300 whitespace-pre-wrap">
                    Patch apply error: {runResult.applied.error}
                  </div>
                )}
                {runResult?.applied?.modified && (
                  <div className="text-xs text-green-300">
                    Patch applied:{' '}
                    {Array.isArray(runResult.applied.modified)
                      ? runResult.applied.modified.join(', ')
                      : String(runResult.applied.modified)}
                  </div>
                )}

                <div className="bg-neutral-900 border border-neutral-800 rounded-md p-3">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{formatResult(runResult.result)}</ReactMarkdown>
                </div>

                {(() => {
                    const patchMeta = runResult?.result?.patch_unified_diff_meta
                    const patchFromResult = runResult?.result?.patch_unified_diff
                    const patchText = (fullPatch ?? patchFromResult) as any
                    const patchStr = typeof patchText === 'string' ? patchText : ''
                    const hasPatch = !!patchStr.trim()
                    const hasMeta = patchMeta && typeof patchMeta === 'object'

                    if (!hasPatch && !hasMeta) return null

                    const metaChars =
                      hasMeta && Number.isFinite(Number((patchMeta as any)?.chars))
                        ? Number((patchMeta as any).chars)
                        : null

                    return (
                      <>
                        <div className="text-xs font-semibold text-neutral-200">Patch (unified diff)</div>

                        {hasPatch ? (
                          <pre className="text-xs bg-neutral-950 border border-neutral-800 rounded-md p-2 overflow-auto max-h-72">
                            {patchStr}
                          </pre>
                        ) : (
                          <div className="text-xs bg-neutral-950 border border-neutral-800 rounded-md p-2">
                            <div className="text-neutral-300">
                              Patch omitted{metaChars != null ? ` (${metaChars} chars)` : ''}. Load it on demand.
                            </div>
                            <button
                              className="mt-2 rounded-md bg-neutral-800 hover:bg-neutral-700 px-3 py-2 text-xs font-semibold disabled:opacity-50"
                              onClick={onLoadFullPatch}
                              disabled={patchBusy || busy || !activeProject || !runResult?.run_id}
                            >
                              {patchBusy ? 'Loading…' : 'Load full patch'}
                            </button>
                          </div>
                        )}
                      </>
                    )
                })()}
              </div>
            )}
          </div>

          <div className="mt-6">
            <div className="text-xs font-semibold text-neutral-200">Recent runs</div>
            <div className="mt-2 flex flex-col gap-2">
              {runs.slice(0, 10).map((r, idx) => {
                const key = r?.id ?? r?.run_id ?? `${r?.created_at ?? 'na'}-${r?.target_path ?? 'na'}-${idx}`
                const rid = Number(r?.id ?? r?.run_id)
                return (
                  <button
                     key={key}
                     type="button"
                     className="text-left text-xs bg-neutral-950 border border-neutral-800 rounded-md p-2 hover:border-neutral-700 disabled:opacity-50"
                     onClick={() => onLoadRun(rid)}
                     disabled={busy || nodeBusy || patchBusy || runLoadBusy || !activeProject || !Number.isFinite(rid)}
                     title="Load this run"
                  >
                    <div className="text-neutral-200 font-semibold">
                      #{r?.id ?? r?.run_id ?? '—'} · {r?.mode ?? '—'} · {r?.target_path ?? '—'}
                    </div>
                    <div className="text-neutral-500">{r?.created_at ?? '—'}</div>
                    <div className="text-neutral-300 line-clamp-2">{r?.prompt ?? '—'}</div>
                  </button>
                )
              })}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
