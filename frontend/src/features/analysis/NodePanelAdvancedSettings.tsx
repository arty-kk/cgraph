import React from 'react'
import type { DepMode, Mode } from '@/api'
import { clampInt } from '@/shared/lib/number'
import { clampFloat } from './NodePanel.helpers'
import { SectionHeader, type HelpTopic } from './NodePanel.sections'

type AutoOrMode = 'auto' | Mode
type RetrievalMode = 'agentic' | 'pack'

type Props = {
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
  busy: boolean
  ctxAdvancedOpen: boolean
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
  setCtxAdvancedOpen: React.Dispatch<React.SetStateAction<boolean>>
  onOpenHelp: (topic: HelpTopic) => void
}

export function NodePanelAdvancedSettings({
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
  busy,
  ctxAdvancedOpen,
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
  setCtxAdvancedOpen,
  onOpenHelp,
}: Props) {
  const controlBase = 'w-full h-9 rounded-md bg-neutral-900 border border-neutral-800 px-2 text-xs outline-none'
  const controlDisabled = 'disabled:opacity-50'
  const controlClass = `${controlBase} ${controlDisabled}`
  const labelRowClass = 'flex items-center gap-2 leading-none'
  const fieldLabelClass = 'text-[11px] font-semibold text-neutral-200'
  const isAuto = mode === 'auto'
  const isAgentic = retrievalMode === 'agentic'
  const patchAllowed = isAuto || mode === 'fix'

  return (
    <div className="mt-2">
      <SectionHeader
        onOpenHelp={onOpenHelp}
        title="Advanced settings"
        topic="ctxSettings"
        open={ctxAdvancedOpen}
        onToggle={() => setCtxAdvancedOpen((v) => !v)}
        toggleTitle="Show/hide advanced settings"
      />

      {ctxAdvancedOpen && (
        <div className="mt-2 space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <div className="text-xs text-neutral-300">
              <div className={labelRowClass}>
                <span className={fieldLabelClass}>Context</span>
              </div>
              <select
                className={controlClass + ' mt-1'}
                value={retrievalMode}
                onChange={(e) => setRetrievalMode(e.target.value as RetrievalMode)}
                disabled={busy}
              >
                <option value="agentic">Agentic</option>
                <option value="pack">Pack Context</option>
              </select>
            </div>

            <div>
              <div className={labelRowClass}>
                <span className={fieldLabelClass}>Mode</span>
              </div>
              <select
                className={controlClass + ' mt-1'}
                value={mode}
                onChange={(e) => setMode(e.target.value as AutoOrMode)}
                disabled={busy}
                title="Auto — choose mode automatically. Analyze — analysis/diagnostics. Evolve — improvement plan. Fix — fix (may include a patch). Impact — what the change affects."
              >
                <option value="auto">Auto</option>
                <option value="analyze">Analyze</option>
                <option value="evolve">Evolve</option>
                <option value="fix">Fix</option>
                <option value="impact">Impact</option>
              </select>
            </div>

            <div>
              <div className={labelRowClass}>
                <span className={fieldLabelClass}>Depth</span>
              </div>
              <input
                type="number"
                className={controlClass + ' mt-1'}
                value={depth}
                min={0}
                max={6}
                title="Dependency capture depth for the mode (except Auto). 0 — file only, higher — deeper in the graph."
                onChange={(e) => {
                  const raw = e.target.value
                  const next = raw === '' ? 1 : clampInt(Number(raw), 0, 6)
                  setDepth(next)
                }}
                disabled={busy || isAuto}
              />
            </div>

            <div>
              <div className={labelRowClass}>
                <span className={fieldLabelClass}>Dependencies</span>
              </div>
              <select
                className={controlClass + ' mt-1'}
                value={depMode}
                onChange={(e) => setDepMode(e.target.value as DepMode)}
                disabled={busy || isAuto || isAgentic}
                title={isAgentic ? 'In agentic mode dep_mode is not used' : 'dep_mode for pack_context'}
              >
                <option value="contracts">Contracts</option>
                <option value="full">Full</option>
              </select>
            </div>

            <label
              className="col-span-2 h-9 rounded-md bg-neutral-900 border border-neutral-800 px-2 flex items-center justify-between gap-2"
              title="If enabled, apply a Unified Diff to the repo (mostly useful for Fix)."
            >
              <span className="text-[11px] font-semibold text-neutral-200">
                Apply patch
              </span>
              <input
                type="checkbox"
                checked={applyPatch}
                onChange={(e) => setApplyPatch(e.target.checked)}
                disabled={busy || !patchAllowed}
              />
            </label>

            <label
              className="col-span-2 h-9 rounded-md bg-neutral-900 border border-neutral-800 px-2 flex items-center justify-between gap-2"
              title={isAgentic ? 'Require evidence for agentic runs.' : 'Only available in agentic mode.'}
            >
              <span className="text-[11px] font-semibold text-neutral-200">
                Require evidence
              </span>
              <input
                type="checkbox"
                checked={agenticEvidenceMode}
                onChange={(e) => setAgenticEvidenceMode(e.target.checked)}
                disabled={busy || !isAgentic}
              />
            </label>
          </div>

          <div className="border-t border-neutral-800 pt-3">
            <div className="text-[11px] font-semibold text-neutral-400">Limits</div>
            <div className="mt-2 grid grid-cols-2 gap-2">
              {isAgentic ? (
                <>
                  <label className="text-xs text-neutral-300">
                    <div className={labelRowClass}>
                      <span className={fieldLabelClass}>Max calls</span>
                    </div>
                    <input
                      type="number"
                      className={controlClass + ' mt-1'}
                      value={agenticMaxCalls}
                      min={1}
                      max={100}
                      onChange={(e) => setAgenticMaxCalls(clampInt(Number(e.target.value || 0), 1, 100))}
                      disabled={busy}
                    />
                  </label>
                  <label className="text-xs text-neutral-300">
                    <div className={labelRowClass}>
                      <span className={fieldLabelClass}>Max file chars</span>
                    </div>
                    <input
                      type="number"
                      className={controlClass + ' mt-1'}
                      value={agenticMaxFileChars}
                      min={1}
                      max={200000}
                      onChange={(e) => setAgenticMaxFileChars(clampInt(Number(e.target.value || 0), 1, 200000))}
                      disabled={busy}
                    />
                  </label>
                  <label className="text-xs text-neutral-300">
                    <div className={labelRowClass}>
                      <span className={fieldLabelClass}>Max tool output</span>
                    </div>
                    <input
                      type="number"
                      className={controlClass + ' mt-1'}
                      value={agenticMaxTotalToolOutputChars}
                      min={1}
                      max={2000000}
                      onChange={(e) => setAgenticMaxTotalToolOutputChars(clampInt(Number(e.target.value || 0), 1, 2000000))}
                      disabled={busy}
                    />
                  </label>
                  <label className="text-xs text-neutral-300">
                    <div className={labelRowClass}>
                      <span className={fieldLabelClass}>Temperature</span>
                    </div>
                    <input
                      type="number"
                      step={0.1}
                      className={controlClass + ' mt-1'}
                      value={agenticTemperature}
                      min={0}
                      max={2}
                      onChange={(e) => setAgenticTemperature(clampFloat(Number(e.target.value || 0), 0, 2))}
                      disabled={busy}
                    />
                  </label>
                </>
              ) : (
                <>
                  <label className="text-xs text-neutral-300">
                    <div className={labelRowClass}>
                      <span className={fieldLabelClass}>Max files</span>
                    </div>
                    <input
                      type="number"
                      className={controlClass + ' mt-1'}
                      value={packMaxFiles}
                      min={1}
                      max={80}
                      onChange={(e) => setPackMaxFiles(clampInt(Number(e.target.value || 0), 1, 80))}
                      disabled={busy}
                    />
                  </label>
                  <label className="text-xs text-neutral-300">
                    <div className={labelRowClass}>
                      <span className={fieldLabelClass}>Max chars/file</span>
                    </div>
                    <input
                      type="number"
                      className={controlClass + ' mt-1'}
                      value={packMaxCharsPerFile}
                      min={1}
                      max={200000}
                      onChange={(e) => setPackMaxCharsPerFile(clampInt(Number(e.target.value || 0), 1, 200000))}
                      disabled={busy}
                    />
                  </label>
                  <label className="text-xs text-neutral-300 col-span-2">
                    <div className={labelRowClass}>
                      <span className={fieldLabelClass}>Max total chars</span>
                    </div>
                    <input
                      type="number"
                      className={controlClass + ' mt-1'}
                      value={packMaxTotalChars}
                      min={1}
                      max={2000000}
                      onChange={(e) => setPackMaxTotalChars(clampInt(Number(e.target.value || 0), 1, 2000000))}
                      disabled={busy}
                    />
                  </label>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
