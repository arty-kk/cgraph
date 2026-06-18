import React, { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Project, RunTaskBody, RunTaskResult } from '@/api'
import { clampInt } from '@/shared/lib/number'
import { formatResult } from '@/shared/lib/formatResult'
import { Modal } from '@/shared/ui/Modal'
import { asStringList, fmtDuration, fmtK, fmtTraceArgs, formatTraceCommand, isRecord } from './NodePanel.helpers'
import { resultMarkdownComponents } from './NodePanel.markdown'

type RetrievalMode = 'agentic' | 'pack'

type Props = {
  open: boolean
  onClose: () => void
  runResult: RunTaskResult | null
  activeRunId: number | null
  runLoadBusy: boolean
  busy: boolean
  activeProject: Project | null
  canRun: boolean
  patchBusy: boolean
  fullPatch: string | null
  notifyInfo: (message: string) => void
  retrievalMode: RetrievalMode
  depth: number
  agenticMaxCalls: number
  agenticMaxFileChars: number
  agenticMaxTotalToolOutputChars: number
  packMaxFiles: number
  packMaxTotalChars: number
  onLoadRun: (runId: number) => void | Promise<void>
  onRunWithExpandedContext: (extra?: Partial<RunTaskBody>) => void | Promise<void>
  onScan: () => void | Promise<void>
  onApplyRunPatch: () => void | Promise<void>
  onLoadFullPatch: () => void | Promise<void>
}

export function NodePanelResultModal({
  open,
  onClose,
  runResult,
  activeRunId,
  runLoadBusy,
  busy,
  activeProject,
  canRun,
  patchBusy,
  fullPatch,
  notifyInfo,
  retrievalMode,
  depth,
  agenticMaxCalls,
  agenticMaxFileChars,
  agenticMaxTotalToolOutputChars,
  packMaxFiles,
  packMaxTotalChars,
  onLoadRun,
  onRunWithExpandedContext,
  onScan,
  onApplyRunPatch,
  onLoadFullPatch,
}: Props) {
  const handleCopy = React.useCallback(
    async (value: string, message: string) => {
      if (!value.trim()) return
      try {
        await navigator.clipboard.writeText(value)
        notifyInfo(message)
      } catch {}
    },
    [notifyInfo]
  )

  const graphScanWarning = runResult?.warning === 'graph not built'

  const runPayload = runResult
    ? {
        ...(isRecord(runResult.result) ? runResult.result : { raw: runResult.result }),
        ...(runResult.plan_tz ? { plan_tz: runResult.plan_tz, plan_source: runResult.plan_source } : {}),
      }
    : null
  const blockedPaths = useMemo(() => {
    const raw = runResult?.applied?.blocked_paths
    if (!Array.isArray(raw)) return []
    return raw.map((p) => (typeof p === 'string' ? p.trim() : '')).filter(Boolean)
  }, [runResult?.applied?.blocked_paths])
  const blockedReason = runResult?.applied?.blocked_reason
  const showBlockedWarning = blockedPaths.length > 0 || blockedReason === 'out_of_context'

  const retrieval = (runResult as any)?.retrieval ?? runResult?.retrieval ?? '—'
  const retrievalSettings = (runResult as any)?.retrieval_settings ?? runResult?.retrieval_settings
  const applyPatchLabel =
    typeof runResult?.apply_patch === 'boolean' ? (runResult.apply_patch ? 'yes' : 'no') : '—'
  const agenticEvidenceValue = isRecord(retrievalSettings)
    && isRecord((retrievalSettings as any).agentic)
    ? (retrievalSettings as any).agentic.agentic_evidence_mode
    : undefined
  const agenticEvidenceLabel =
    typeof agenticEvidenceValue === 'boolean' ? (agenticEvidenceValue ? 'yes' : 'no') : '—'

  const retrievalSummary = useMemo(() => {
    if (!isRecord(retrievalSettings)) return null

    if (retrieval === 'agentic') {
      const a = (retrievalSettings as any).agentic
      if (!isRecord(a)) return 'ctx: agentic'
      const callsUsed = (a as any).tool_calls_used
      const callsMax = (a as any).max_calls
      const cache = (a as any).cache_hits
      const files = (a as any).files_read
      const outChars = (a as any).tool_output_chars_used
      const outMax = (a as any).max_total_tool_output_chars
      return `ctx: agentic · calls ${Number.isFinite(Number(callsUsed)) ? Number(callsUsed) : '—'}/${Number.isFinite(Number(callsMax)) ? Number(callsMax) : '—'} · cache ${Number.isFinite(Number(cache)) ? Number(cache) : 0} · files ${Number.isFinite(Number(files)) ? Number(files) : '—'} · tool chars ${fmtK(outChars)}${outMax != null ? `/${fmtK(outMax)}` : ''}`
    }

    if (retrieval === 'pack') {
      const p = (retrievalSettings as any).pack
      if (!isRecord(p)) return 'ctx: pack'
      return `ctx: pack · max_files ${p.max_files ?? '—'} · chars/file ${fmtK(p.max_chars_per_file)} · total ${fmtK(p.max_total_chars)}`
    }

    if (retrieval === 'graph') return 'ctx: graph'
    return `ctx: ${String(retrieval)}`
  }, [fmtK, isRecord, retrieval, retrievalSettings])

  const agenticSettings = useMemo(() => {
    if (!isRecord(retrievalSettings)) return null
    const a = (retrievalSettings as any).agentic
    if (!isRecord(a)) return null
    return a as Record<string, unknown>
  }, [isRecord, retrievalSettings])

  const packSettings = useMemo(() => {
    if (!isRecord(retrievalSettings)) return null
    const p = (retrievalSettings as any).pack
    if (!isRecord(p)) return null
    return p as Record<string, unknown>
  }, [isRecord, retrievalSettings])

  const graphSettings = useMemo(() => {
    if (!isRecord(retrievalSettings)) return null
    const g = (retrievalSettings as any).graph
    if (!isRecord(g)) return null
    return g as Record<string, unknown>
  }, [isRecord, retrievalSettings])

  const agenticTrace = useMemo(() => {
    if (retrieval !== 'agentic' || !isRecord(retrievalSettings)) return []
    const a = (retrievalSettings as any).agentic
    if (!isRecord(a)) return []
    const trace = (a as any).tool_trace
    if (!Array.isArray(trace)) return []
    return trace.filter((entry) => isRecord(entry))
  }, [isRecord, retrieval, retrievalSettings])

  const retrievalPlan = useMemo(() => {
    if (!agenticSettings || !isRecord(agenticSettings)) return null
    const plan = (agenticSettings as any).retrieval_plan
    if (!plan) return null
    if (Array.isArray(plan)) return plan
    if (isRecord(plan)) {
      return Object.entries(plan).map(([key, value]) => `${key}: ${String(value)}`)
    }
    return [String(plan)]
  }, [agenticSettings, isRecord])

  const missingContextHints = useMemo(() => {
    if (!agenticSettings) return []
    const direct = asStringList((agenticSettings as any).self_check_missing_context)
    const retry = asStringList((agenticSettings as any).self_check_retry_missing_context)
    return Array.from(new Set([...direct, ...retry])).filter(Boolean)
  }, [agenticSettings, asStringList])

  const suggestedOverrides = useMemo(() => {
    if (retrievalMode === 'agentic' && agenticSettings) {
      const multiplier = (agenticSettings as any).self_check_retry_multiplier
      if (isRecord(multiplier)) {
        return {
          agentic_max_calls: Number(multiplier.max_calls ?? agenticSettings.max_calls ?? agenticMaxCalls),
          agentic_max_file_chars: Number(
            multiplier.max_file_chars ?? agenticSettings.max_file_chars ?? agenticMaxFileChars
          ),
          agentic_max_total_tool_output_chars: Number(
            multiplier.max_total_tool_output_chars
              ?? agenticSettings.max_total_tool_output_chars
              ?? agenticMaxTotalToolOutputChars
          ),
        } as Partial<RunTaskBody>
      }
      return {
        agentic_max_calls: clampInt(Number(agenticSettings.max_calls ?? agenticMaxCalls) + 10, 1, 100),
        agentic_max_file_chars: clampInt(Number(agenticSettings.max_file_chars ?? agenticMaxFileChars), 1, 200_000),
        agentic_max_total_tool_output_chars: clampInt(
          Number(agenticSettings.max_total_tool_output_chars ?? agenticMaxTotalToolOutputChars),
          1,
          2_000_000,
        ),
      } as Partial<RunTaskBody>
    }
    if (retrievalMode === 'pack' && packSettings) {
      return {
        depth: clampInt(depth + 1, 1, 6),
        pack_max_files: clampInt(Number(packSettings.max_files ?? packMaxFiles) + 10, 1, 200),
        pack_max_total_chars: clampInt(
          Number(packSettings.max_total_chars ?? packMaxTotalChars) + 50_000,
          1,
          2_000_000,
        ),
      } as Partial<RunTaskBody>
    }
    return null
  }, [
    agenticMaxCalls,
    agenticMaxFileChars,
    agenticMaxTotalToolOutputChars,
    agenticSettings,
    depth,
    packMaxFiles,
    packMaxTotalChars,
    packSettings,
    retrievalMode,
  ])

  const isActiveRunLoaded = activeRunId == null || runResult?.run_id === activeRunId

  const resultText = useMemo(
    () => formatResult(runPayload as Record<string, any> | null),
    [runPayload],
  )

  return (
    <Modal
      open={open}
      title="Result"
      onClose={onClose}
    >
      <div className="space-y-4">
        {runLoadBusy ? (
          <div className="text-xs text-neutral-500">Loading run…</div>
        ) : !isActiveRunLoaded ? (
          <div className="space-y-2">
            <div className="text-xs text-neutral-500">Run data is not loaded.</div>
            <button
              type="button"
              className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold disabled:opacity-50"
              onClick={async () => {
                if (!Number.isFinite(activeRunId)) return
                await onLoadRun(Number(activeRunId))
              }}
              disabled={!Number.isFinite(activeRunId) || busy || !activeProject}
            >
              Retry
            </button>
          </div>
        ) : !runResult ? (
          <div className="text-xs text-neutral-500">—</div>
        ) : (
          <>
            <div className="text-xs text-neutral-400">
              run_id: {runResult?.run_id ?? '—'} · mode: {runResult?.mode ?? '—'} · depth:{' '}
              {runResult?.depth ?? '—'} · dep_mode: {runResult?.dep_mode ?? '—'} · retrieval:{' '}
              {String(retrieval)} · apply_patch: {applyPatchLabel} · evidence: {agenticEvidenceLabel}
            </div>
            {retrievalSummary && (
              <div className="text-[11px] text-neutral-500 whitespace-pre-wrap">{retrievalSummary}</div>
            )}
            {(retrievalPlan || missingContextHints.length > 0) && (
              <div className="rounded-md border border-neutral-800 bg-neutral-950/60 px-3 py-2 text-[11px] text-neutral-300 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-xs font-semibold text-neutral-200">Retrieval diagnostics</div>
                  <button
                    type="button"
                    className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[10px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
                    onClick={() => onRunWithExpandedContext(suggestedOverrides ?? undefined)}
                    disabled={!canRun || busy}
                    title="Re-run with suggested context limits"
                  >
                    Re-run with context
                  </button>
                </div>
                {retrievalPlan && (
                  <div>
                    <div className="text-[10px] uppercase tracking-wide text-neutral-500">Plan</div>
                    <div className="mt-1 whitespace-pre-wrap text-neutral-400">
                      {Array.isArray(retrievalPlan) ? retrievalPlan.join('\n') : String(retrievalPlan)}
                    </div>
                  </div>
                )}
                <div>
                  <div className="text-[10px] uppercase tracking-wide text-neutral-500">Missing context</div>
                  <div className="mt-1 text-neutral-400">
                    {missingContextHints.length > 0 ? missingContextHints.join('; ') : '—'}
                  </div>
                </div>
              </div>
            )}
            <div className="rounded-md border border-neutral-800 bg-neutral-950/50 px-3 py-2 text-[11px] text-neutral-400 space-y-1">
              <div className="text-xs font-semibold text-neutral-200">Quality / Context</div>
              <div>
                Agentic limits:{' '}
                {agenticSettings ? (
                  <>
                    calls {fmtK(agenticSettings.tool_calls_used)}/{fmtK(agenticSettings.max_calls)} · tool chars{' '}
                    {fmtK(agenticSettings.tool_output_chars_used)}/{fmtK(agenticSettings.max_total_tool_output_chars)} · file chars{' '}
                    {fmtK(agenticSettings.max_file_chars)} · temp {agenticSettings.temperature ?? '—'} · effort{' '}
                    {agenticSettings.reasoning_effort ?? '—'}
                  </>
                ) : (
                  '—'
                )}
              </div>
              <div>
                Pack limits:{' '}
                {packSettings ? (
                  <>
                    max_files {packSettings.max_files ?? '—'} · chars/file {fmtK(packSettings.max_chars_per_file)} · total{' '}
                    {fmtK(packSettings.max_total_chars)}
                  </>
                ) : (
                  '—'
                )}
              </div>
              <div>
                Graph limits:{' '}
                {graphSettings ? (
                  <>
                    max_nodes {graphSettings.max_nodes ?? '—'} · max_depth {graphSettings.max_depth ?? '—'}
                    {typeof graphSettings.truncated === 'boolean' ? ` · truncated ${graphSettings.truncated ? 'yes' : 'no'}` : ''}
                  </>
                ) : (
                  '—'
                )}
              </div>
              <div>
                Budget reason:{' '}
                {agenticSettings ? (
                  asStringList(agenticSettings.budget_reason).join(', ') || '—'
                ) : (
                  '—'
                )}
              </div>
              <div>
                Self-check missing context:{' '}
                {agenticSettings ? (
                  asStringList(agenticSettings.self_check_missing_context).join('; ') || '—'
                ) : (
                  '—'
                )}
              </div>
              <div>
                Self-check retry:{' '}
                {agenticSettings ? (
                  agenticSettings.self_check_retry ? (
                    <>
                      yes
                      {isRecord(agenticSettings.self_check_retry_multiplier)
                        ? ` · calls x${agenticSettings.self_check_retry_multiplier.max_calls ?? '—'} · tool chars x${agenticSettings.self_check_retry_multiplier.max_total_tool_output_chars ?? '—'} · file chars x${agenticSettings.self_check_retry_multiplier.max_file_chars ?? '—'}`
                        : ''}
                    </>
                  ) : (
                    'no'
                  )
                ) : (
                  '—'
                )}
              </div>
              <div className="text-[10px] text-neutral-500">
                Effective limits reflect server caps, complexity-based scaling (depth, prompt size, project size, mode),
                and an optional single retry when self-check reports missing context.
              </div>
            </div>
            {graphScanWarning && (
              <div className="text-xs bg-amber-950/40 border border-amber-800 rounded-md p-2 text-amber-200 space-y-2">
                <div>
                  Graph index is stale. Start Scan/Rescan now to rebuild it and then rerun analysis for complete context.
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="rounded-md bg-amber-900/40 hover:bg-amber-900/60 border border-amber-800 px-3 py-1 text-[11px] font-semibold disabled:opacity-50"
                    onClick={() => onScan()}
                    disabled={!activeProject || busy}
                  >
                    Scan/Rescan now
                  </button>
                </div>
              </div>
            )}
            {agenticTrace.length > 0 && (
              <div className="mt-3">
                <div className="text-xs font-semibold text-neutral-200">Static analysis trace</div>
                <div className="mt-2 space-y-2">
                  {agenticTrace.map((entry, idx) => {
                    const status = String((entry as any).status || '—')
                    const ok = status === 'ok'
                    const statusIcon = ok ? '✅' : '❌'
                    const commandLine = formatTraceCommand(entry)
                    return (
                      <div
                        key={`${(entry as any).name ?? 'tool'}-${idx}`}
                        className="rounded-md border border-neutral-800 bg-neutral-950/60 px-2 py-2 text-xs"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="font-mono text-[11px] text-indigo-200 break-all">
                            {statusIcon} {commandLine}
                          </div>
                          <div className="flex flex-wrap items-center gap-2 text-[11px] text-neutral-400">
                            <span className={ok ? 'text-emerald-300' : 'text-red-300'}>
                              {status}
                            </span>
                            <span>{(entry as any).cache_hit ? 'cache hit' : 'cache miss'}</span>
                            <span>{fmtDuration((entry as any).duration_ms)}</span>
                            <span>{fmtK((entry as any).response_chars)} chars</span>
                          </div>
                        </div>
                        <div className="mt-1 text-[11px] text-neutral-500">
                          args:{' '}
                          <span className="font-mono text-neutral-300">
                            {fmtTraceArgs((entry as any).args)}
                          </span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {runResult?.applied?.error && (
              <div className="text-xs text-red-300 whitespace-pre-wrap">
                Patch Apply Error: {runResult.applied.error}
              </div>
            )}
            {showBlockedWarning && (
              <div className="rounded-md border border-amber-800 bg-amber-950/40 p-3 text-xs text-amber-200">
                <div className="font-semibold">Patch out of context</div>
                {blockedPaths.length > 0 ? (
                  <ul className="mt-2 list-disc space-y-1 pl-4 text-amber-100">
                    {blockedPaths.map((path) => (
                      <li key={path} className="font-mono">
                        {path}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="mt-2 text-amber-100">
                    Patch touches files outside the current context.
                  </div>
                )}
                <button
                  type="button"
                  className="mt-3 rounded-md bg-amber-900/60 hover:bg-amber-900/80 border border-amber-700 px-3 py-1 text-[11px] font-semibold disabled:opacity-50"
                  onClick={() => onRunWithExpandedContext()}
                  disabled={!canRun || busy}
                >
                  Retry with expanded context
                </button>
              </div>
            )}
            {runResult?.applied?.modified && (
              <div className="text-xs text-green-300">
                Patch Applied:{' '}
                {Array.isArray(runResult.applied.modified)
                  ? runResult.applied.modified.join(', ')
                  : String(runResult.applied.modified)}
              </div>
            )}

            <div className="flex items-center justify-between gap-2 text-xs font-semibold text-neutral-200">
              <div>Context</div>
              <button
                type="button"
                className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold disabled:opacity-50"
                onClick={async () => {
                  if (!resultText.trim()) return
                  await handleCopy(resultText, 'Result copied')
                }}
                disabled={!resultText.trim()}
              >
                Copy
              </button>
            </div>
            <div className="text-xs bg-neutral-950 border border-neutral-800 rounded-md p-3 overflow-auto max-h-[45vh]">
              {!resultText.trim() ? (
                <div className="text-neutral-500">—</div>
              ) : (
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={resultMarkdownComponents}>
                  {resultText}
                </ReactMarkdown>
              )}
            </div>

            {(() => {
              const patchMeta = isRecord(runResult?.result)
                ? runResult?.result?.patch_unified_diff_meta
                : undefined
              const patchFromResult = isRecord(runResult?.result)
                ? runResult?.result?.patch_unified_diff
                : undefined
              const patchText = fullPatch ?? patchFromResult
              const patchStr = typeof patchText === 'string' ? patchText : ''
              const hasPatch = !!patchStr.trim()
              const hasMeta = patchMeta && typeof patchMeta === 'object'
              const canApplyPatch = Boolean(runResult?.run_id && (hasPatch || hasMeta))

              if (!hasPatch && !hasMeta) {
                return (
                  <div className="text-xs text-neutral-500">
                    Patch — none for this run.
                  </div>
                )
              }

              const metaChars =
                hasMeta && Number.isFinite(Number((patchMeta as any)?.chars))
                  ? Number((patchMeta as any).chars)
                  : null

              return (
                <>
                  <div className="flex items-center justify-between gap-2 text-xs font-semibold text-neutral-200">
                    <div>Patch (Unified Diff)</div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold disabled:opacity-50"
                        onClick={async () => {
                          if (!patchStr) return
                          await handleCopy(patchStr, 'Patch copied')
                        }}
                        disabled={!patchStr}
                        title={patchStr ? 'Copy patch' : 'No patch to copy'}
                      >
                        Copy
                      </button>
                      <button
                        type="button"
                        className="rounded-md bg-emerald-900/70 hover:bg-emerald-900/90 border border-emerald-700 px-2 py-1 text-[11px] font-semibold disabled:opacity-50"
                        onClick={async () => {
                          if (!canApplyPatch) return
                          if (!window.confirm('Apply this patch to the project now?')) return
                          await onApplyRunPatch()
                        }}
                        disabled={!canApplyPatch || busy || patchBusy}
                        title={canApplyPatch ? 'Apply patch now' : 'No patch to apply'}
                      >
                        Apply patch now
                      </button>
                    </div>
                  </div>

                  {hasPatch ? (
                    <pre className="text-xs bg-neutral-950 border border-neutral-800 rounded-md p-2 overflow-auto max-h-72">
                      {patchStr}
                    </pre>
                  ) : (
                    <div className="text-xs bg-neutral-950 border border-neutral-800 rounded-md p-2">
                      <div className="text-neutral-300">
                        Patch Omitted{metaChars != null ? ` (${metaChars} chars)` : ''}. Load it on demand.
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
          </>
        )}
      </div>
    </Modal>
  )
}
