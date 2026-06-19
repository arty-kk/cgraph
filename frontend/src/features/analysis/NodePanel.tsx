// frontend/src/ui/components/NodePanel.tsx
import React, { useMemo } from 'react'
import type { DepMode, Mode, NodeContract, NodeInfo, Project, RunRecord, RunTaskBody, RunTaskResult } from '@/api'
import { clampInt } from '@/shared/lib/number'
import { safeStorageGet, safeStorageSet } from '@/shared/lib/storage'
import { LanguageIcon } from '@/shared/ui/LanguageIcon'
import { NodePanelHelpModal } from './NodePanel.HelpModal'
import { NodePanelResultModal } from './NodePanelResultModal'
import { clampFloat } from './NodePanel.helpers'
import { SectionHeader } from './NodePanel.sections'
import { NodePanelRunsList } from './NodePanelRunsList'
import { NodePanelAdvancedSettings } from './NodePanelAdvancedSettings'
import { NodePanelPromptInput } from './NodePanelPromptInput'

type AutoOrMode = 'auto' | Mode
type RetrievalMode = 'agentic' | 'pack'

type Props = {
  activeProject: Project | null
  selectedPath: string | null
  selectedInGraph: boolean
  graphTruncated: boolean
  onLoadFullGraph: () => void | Promise<void>
  onHidePanel?: () => void
  notifyInfo: (message: string) => void
  onScan: () => void | Promise<void>

  nodeBusy: boolean
  nodeInfo: NodeInfo | null
  contract: NodeContract | null
  busy: boolean
  mode: AutoOrMode
  depth: number
  depMode: DepMode
  retrievalMode: RetrievalMode
  agenticMaxCalls: number
  agenticMaxFileChars: number
  agenticMaxTotalToolOutputChars: number
  agenticTemperature: number
  agenticEvidenceMode: boolean
  packMaxFiles: number
  packMaxCharsPerFile: number
  packMaxTotalChars: number
  applyPatch: boolean
  prompt: string

  setMode: (v: AutoOrMode) => void
  setDepth: (v: number) => void
  setDepMode: (v: DepMode) => void
  setRetrievalMode: (v: RetrievalMode) => void
  setAgenticMaxCalls: (v: number) => void
  setAgenticMaxFileChars: (v: number) => void
  setAgenticMaxTotalToolOutputChars: (v: number) => void
  setAgenticTemperature: (v: number) => void
  setAgenticEvidenceMode: (v: boolean) => void
  setPackMaxFiles: (v: number) => void
  setPackMaxCharsPerFile: (v: number) => void
  setPackMaxTotalChars: (v: number) => void
  setApplyPatch: (v: boolean) => void
  setPrompt: (v: string) => void

  canRun: boolean
  onRun: () => void | Promise<void>
  onRunWithExpandedContext: (extra?: Partial<RunTaskBody>) => void | Promise<void>

  runResult: RunTaskResult | null
  fullPatch: string | null
  patchBusy: boolean
  runLoadBusy: boolean
  onLoadFullPatch: () => void | Promise<void>
  onApplyRunPatch: () => void | Promise<void>
  onLoadRun: (runId: number) => void | Promise<void>
  onDeleteRun: (runId: number) => void | Promise<void>
  runs: RunRecord[]
}

export function NodePanel({
  activeProject,
  onHidePanel,
  selectedPath,
  selectedInGraph,
  graphTruncated,
  onLoadFullGraph,
  nodeBusy,
  notifyInfo,
  onScan,
  nodeInfo,
  contract,
  busy,
  mode,
  depth,
  depMode,
  retrievalMode,
  agenticMaxCalls,
  agenticMaxFileChars,
  agenticMaxTotalToolOutputChars,
  agenticTemperature,
  agenticEvidenceMode,
  packMaxFiles,
  packMaxCharsPerFile,
  packMaxTotalChars,
  applyPatch,
  prompt,
  setMode,
  setDepth,
  setDepMode,
  setRetrievalMode,
  setAgenticMaxCalls,
  setAgenticMaxFileChars,
  setAgenticMaxTotalToolOutputChars,
  setAgenticTemperature,
  setAgenticEvidenceMode,
  setPackMaxFiles,
  setPackMaxCharsPerFile,
  setPackMaxTotalChars,
  setApplyPatch,
  setPrompt,
  canRun,
  onRun,
  onRunWithExpandedContext,
  runResult,
  fullPatch,
  patchBusy,
  runLoadBusy,
  onLoadFullPatch,
  onApplyRunPatch,
  onLoadRun,
  onDeleteRun,
  runs,
}: Props) {

  const [helpOpen, setHelpOpen] = React.useState<null | 'details' | 'contract' | 'run' | 'runs' | 'ctxSettings'>(null)
  const [resultOpen, setResultOpen] = React.useState(false)
  const [activeRunId, setActiveRunId] = React.useState<number | null>(null)
  const [openedRunId, setOpenedRunId] = React.useState<number | null>(null)
  const [newRunId, setNewRunId] = React.useState<number | null>(null)

  const [detailsOpen, setDetailsOpen] = React.useState<boolean>(() => {
    return (safeStorageGet('cs.ui.detailsOpen', '1') || '1') !== '0'
  })
  React.useEffect(() => {
    safeStorageSet('cs.ui.detailsOpen', detailsOpen ? '1' : '0')
  }, [detailsOpen])

  const [runOpen, setRunOpen] = React.useState<boolean>(() => {
    return (safeStorageGet('cs.ui.runOpen', '1') || '1') !== '0'
  })
  React.useEffect(() => {
    safeStorageSet('cs.ui.runOpen', runOpen ? '1' : '0')
  }, [runOpen])

  const [contractOpen, setContractOpen] = React.useState<boolean>(() => {
    return (safeStorageGet('cs.ui.contractOpen', '') || '') === '1'
  })
  React.useEffect(() => {
    safeStorageSet('cs.ui.contractOpen', contractOpen ? '1' : '0')
  }, [contractOpen])


  const isAuto = mode === 'auto'
  const isAgentic = retrievalMode === 'agentic'
  const patchAllowed = isAuto || mode === 'fix'

  React.useEffect(() => {
    if (applyPatch && !patchAllowed) setApplyPatch(false)
  }, [applyPatch, patchAllowed, setApplyPatch])

  const [ctxAdvancedOpen, setCtxAdvancedOpen] = React.useState<boolean>(() => {
    return (safeStorageGet('cs.ui.ctxAdvancedOpen', '') || '') === '1'
  })
  React.useEffect(() => {
    safeStorageSet('cs.ui.ctxAdvancedOpen', ctxAdvancedOpen ? '1' : '0')
  }, [ctxAdvancedOpen])


  const promptPlaceholder =
    isAuto
      ? 'Describe a task for the selected file. Examples: "explain purpose and risks", "propose a refactor", "fix a bug and add a test", "show impact of change X".'
      : mode === 'analyze'
        ? 'Example: "Briefly describe the file purpose, find risk hot spots, and suggest improvements".'
        : mode === 'evolve'
          ? 'Example: "Propose a safe improvement/refactor plan: steps, affected areas, tests".'
          : mode === 'fix'
            ? 'Example: "Fix <problem description> without breaking the contract; add/update tests. Return a patch".'
            : mode === 'impact'
              ? 'Example: "If we change <symbol/behavior>, which files/modules are affected?"'
              : 'Describe the task.'


  const runDisabledReasons = useMemo(() => {
    const r: string[] = []
    if (!activeProject) r.push('project not selected')
    if (!selectedPath) r.push('file not selected')
    if (!prompt.trim()) r.push('prompt is empty')
    if (busy) r.push('busy')
    if (nodeBusy) r.push('loading node')
    if (activeProject && selectedPath && !nodeInfo && !contract) r.push('node data not ready (Scan/Refresh)')
    return r
  }, [activeProject, busy, contract, nodeBusy, nodeInfo, prompt, selectedPath])



  const showRunFooter = Boolean(selectedPath && runOpen)

  React.useEffect(() => {
    if (!runResult?.run_id) return
    if (openedRunId !== runResult.run_id) setNewRunId(runResult.run_id)
  }, [openedRunId, runResult?.run_id])




  return (
    <div className="relative h-full min-h-0 border-l border-neutral-800 overflow-visible">
      {/* Handle OUTSIDE the panel (into the graph area) */}
      {onHidePanel && (
        <button
          type="button"
          className="absolute -left-2 top-1/2 -translate-y-1/2 z-20 rounded-md bg-neutral-950/80 border border-neutral-700 px-1 py-2 text-xs font-semibold text-neutral-200 hover:bg-neutral-900 shadow-lg"
          onMouseDown={(e) => { e.preventDefault(); e.stopPropagation() }}
          onClick={() => onHidePanel?.()}
          aria-label="Hide right panel"
          title="Hide right panel"
        >
          {'>'}
        </button>
      )}

      {/* Scrollable content */}
      <div className="h-full min-h-0 overflow-auto">
        <div className={['p-4', showRunFooter ? 'pb-28' : 'pb-4'].join(' ')}>
          <div className="mb-2">
            <SectionHeader
              onOpenHelp={setHelpOpen}
              title={selectedPath ? 'Details' : 'No selection'}
              topic="details"
              open={!!selectedPath && detailsOpen}
              onToggle={selectedPath ? () => setDetailsOpen((v) => !v) : undefined}
              toggleTitle="Show/hide node details"
            />
          </div>

          {!selectedPath ? (
            <div className="text-sm text-neutral-300">Pick a file via search or click on the graph.</div>
          ) : (
            <>
              <div className="text-sm font-semibold truncate" title={selectedPath}>{selectedPath}</div>
              
              {!detailsOpen && nodeInfo && (
                <div className="mt-1 text-[11px] text-neutral-500">
                  <span className="inline-flex items-center gap-1">
                    <LanguageIcon language={nodeInfo.language ?? ''} className="h-3 w-3" />
                    <span>· loc {Number.isFinite(Number(nodeInfo.loc)) ? Number(nodeInfo.loc) : '—'} · in {Number(nodeInfo.fan_in ?? 0)} · out {Number(nodeInfo.fan_out ?? 0)}</span>
                  </span>
                </div>
              )}

              {detailsOpen && !selectedInGraph && graphTruncated && (
                <div className="mt-2 text-xs bg-neutral-950 border border-neutral-800 rounded-md p-2">
                  <div className="text-neutral-300">
                    This file is not in the current graph (graph limited / top-N). This is not a file error.
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

              {detailsOpen && !nodeBusy && selectedPath && !selectedInGraph && !graphTruncated && (
                <div className="mt-2 text-xs text-amber-300 whitespace-pre-wrap">
                  File is missing from the graph (maybe deleted/renamed or not indexed yet).
                  {'\n'}
                  Run Scan or Refresh.
                </div>
              )}

              {detailsOpen && nodeBusy ? (
                <div className="mt-2 text-xs text-neutral-400">Loading node…</div>
              ) : detailsOpen ? (
                nodeInfo && (
                  <div className="mt-2 text-xs text-neutral-300 grid grid-cols-2 gap-2">
                    <div>
                      LANG: <LanguageIcon language={nodeInfo.language ?? ''} className="h-3.5 w-3.5" />
                    </div>
                    <div>
                      LOC: <span className="text-neutral-100">{nodeInfo.loc}</span>
                    </div>
                    <div>
                      Fan In: <span className="text-neutral-100">{nodeInfo.fan_in}</span>
                    </div>
                    <div>
                      Fan Out: <span className="text-neutral-100">{nodeInfo.fan_out}</span>
                    </div>
                    <div>
                      Complexity: <span className="text-neutral-100">{nodeInfo.complexity}</span>
                    </div>
                    <div>
                      SCC: <span className="text-neutral-100">{nodeInfo.scc_id}</span>
                    </div>
                    <div>
                      Status: <span className="text-neutral-100">{nodeInfo.status}</span>
                    </div>
                  </div>
                )
              ) : null}

              <div className="mt-3">
                <SectionHeader
                  onOpenHelp={setHelpOpen}
                  title="Contract"
                  topic="contract"
                  open={contractOpen}
                  onToggle={() => setContractOpen((v) => !v)}
                  toggleTitle="Show/hide contract"
                />
                {contractOpen && (
                  <pre className="mt-1 text-xs bg-neutral-900 border border-neutral-800 rounded-md p-2 overflow-auto max-h-40">
                    {nodeBusy ? 'Loading…' : contract ? JSON.stringify(contract, null, 2) : '—'}
                  </pre>
                )}
              </div>

              <div className="mt-3">
                <SectionHeader
                  onOpenHelp={setHelpOpen}
                  title="Run Task"
                  topic="run"
                  open={runOpen}
                  onToggle={() => setRunOpen((v) => !v)}
                  toggleTitle="Show/hide run task section"
                />

                {runOpen && (
                  <>
                    {runResult?.warning && (
                      <div className="mt-2 text-xs bg-amber-950/40 border border-amber-800 rounded-md p-2 text-amber-200 space-y-2">
                        <div>
                          Graph index is incomplete. Run Scan/Rescan now to refresh context before relying on this result.
                        </div>
                        <button
                          type="button"
                          className="rounded-md bg-amber-900/40 hover:bg-amber-900/60 border border-amber-800 px-3 py-1 text-[11px] font-semibold disabled:opacity-50"
                          onClick={() => onScan()}
                          disabled={!activeProject || busy}
                        >
                          Scan/Rescan now
                        </button>
                      </div>
                    )}

                    <NodePanelPromptInput
                      prompt={prompt}
                      setPrompt={setPrompt}
                      promptPlaceholder={promptPlaceholder}
                      busy={busy}
                      setMode={setMode}
                    />

                    <NodePanelAdvancedSettings
                      mode={mode}
                      depth={depth}
                      depMode={depMode}
                      retrievalMode={retrievalMode}
                      agenticMaxCalls={agenticMaxCalls}
                      agenticMaxFileChars={agenticMaxFileChars}
                      agenticMaxTotalToolOutputChars={agenticMaxTotalToolOutputChars}
                      agenticTemperature={agenticTemperature}
                      agenticEvidenceMode={agenticEvidenceMode}
                      packMaxFiles={packMaxFiles}
                      packMaxCharsPerFile={packMaxCharsPerFile}
                      packMaxTotalChars={packMaxTotalChars}
                      applyPatch={applyPatch}
                      busy={busy}
                      ctxAdvancedOpen={ctxAdvancedOpen}
                      setMode={setMode}
                      setDepth={setDepth}
                      setDepMode={setDepMode}
                      setRetrievalMode={setRetrievalMode}
                      setAgenticMaxCalls={setAgenticMaxCalls}
                      setAgenticMaxFileChars={setAgenticMaxFileChars}
                      setAgenticMaxTotalToolOutputChars={setAgenticMaxTotalToolOutputChars}
                      setAgenticTemperature={setAgenticTemperature}
                      setAgenticEvidenceMode={setAgenticEvidenceMode}
                      setPackMaxFiles={setPackMaxFiles}
                      setPackMaxCharsPerFile={setPackMaxCharsPerFile}
                      setPackMaxTotalChars={setPackMaxTotalChars}
                      setApplyPatch={setApplyPatch}
                      setCtxAdvancedOpen={setCtxAdvancedOpen}
                      onOpenHelp={setHelpOpen}
                    />

                  </>
                )}
              </div>

              <NodePanelRunsList
                runs={runs}
                activeProject={activeProject}
                busy={busy}
                nodeBusy={nodeBusy}
                patchBusy={patchBusy}
                runLoadBusy={runLoadBusy}
                runResult={runResult}
                activeRunId={activeRunId}
                newRunId={newRunId}
                onLoadRun={onLoadRun}
                onDeleteRun={onDeleteRun}
                onOpenHelp={setHelpOpen}
                setActiveRunId={setActiveRunId}
                setNewRunId={setNewRunId}
                setOpenedRunId={setOpenedRunId}
                setResultOpen={setResultOpen}
              />
            </>
          )}
        </div>

        {/* Sticky footer: Run controls (always available while working in Run Task) */}
        {showRunFooter && (
          <div className="sticky bottom-0 z-10 border-t border-neutral-800 bg-neutral-950/90 backdrop-blur">
            <div className="px-4 pt-3 pb-4 space-y-2">
              <button
                className="w-full rounded-md bg-indigo-600 hover:bg-indigo-500 px-3 py-2 text-sm font-semibold disabled:opacity-50"
                onClick={() => onRun()}
                disabled={!canRun}
                title={runDisabledReasons.length ? `Run disabled: ${runDisabledReasons.join(', ')}` : 'Run'}
              >
                {busy ? 'Running...' : 'Run'}
              </button>

              {!canRun && runDisabledReasons.length > 0 && (
                <div className="text-[11px] text-neutral-500">
                  Disabled: <span className="text-neutral-300">{runDisabledReasons[0]}</span>
                  {runDisabledReasons.length > 1 ? (
                    <span className="text-neutral-500"> (+{runDisabledReasons.length - 1})</span>
                  ) : null}
                </div>
              )}
            </div>
          </div>
        )}


        <NodePanelResultModal
          open={resultOpen}
          onClose={() => {
            setResultOpen(false)
            setActiveRunId(null)
          }}
          runResult={runResult}
          activeRunId={activeRunId}
          runLoadBusy={runLoadBusy}
          busy={busy}
          activeProject={activeProject}
          canRun={canRun}
          patchBusy={patchBusy}
          fullPatch={fullPatch}
          notifyInfo={notifyInfo}
          retrievalMode={retrievalMode}
          depth={depth}
          agenticMaxCalls={agenticMaxCalls}
          agenticMaxFileChars={agenticMaxFileChars}
          agenticMaxTotalToolOutputChars={agenticMaxTotalToolOutputChars}
          packMaxFiles={packMaxFiles}
          packMaxTotalChars={packMaxTotalChars}
          onLoadRun={onLoadRun}
          onRunWithExpandedContext={onRunWithExpandedContext}
          onScan={onScan}
          onApplyRunPatch={onApplyRunPatch}
          onLoadFullPatch={onLoadFullPatch}
        />
        <NodePanelHelpModal helpOpen={helpOpen} onClose={() => setHelpOpen(null)} />
      </div>
    </div>
  )
}
