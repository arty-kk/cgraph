import React, { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Project, RunTaskBody, RunTaskResult } from '@/api'
import { formatResult } from '@/shared/lib/formatResult'
import { Modal } from '@/shared/ui/Modal'
import { isRecord } from '../lib/NodePanel.helpers'
import { resultMarkdownComponents } from './NodePanel.markdown'
import { NodePanelRetrievalDetails } from './NodePanelRetrievalDetails'

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

            <NodePanelRetrievalDetails
              runResult={runResult}
              retrievalMode={retrievalMode}
              depth={depth}
              agenticMaxCalls={agenticMaxCalls}
              agenticMaxFileChars={agenticMaxFileChars}
              agenticMaxTotalToolOutputChars={agenticMaxTotalToolOutputChars}
              packMaxFiles={packMaxFiles}
              packMaxTotalChars={packMaxTotalChars}
              busy={busy}
              canRun={canRun}
              activeProject={activeProject}
              onRunWithExpandedContext={onRunWithExpandedContext}
              onScan={onScan}
            />

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
