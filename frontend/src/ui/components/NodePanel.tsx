// frontend/src/ui/components/NodePanel.tsx
import React, { useMemo } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { DepMode, Mode, NodeContract, NodeInfo, Project, RunRecord, RunTaskResult } from '../../api'
import { getTaskStatus } from '../../api'
import { clampInt } from '../../lib/number'
import { formatResult } from '../../lib/formatResult'
import { Modal } from './Modal'
import { LanguageIcon } from './LanguageIcon'

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
  onRunWithExpandedContext: () => void | Promise<void>

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

  const promptRef = React.useRef<HTMLTextAreaElement | null>(null)
  const [helpOpen, setHelpOpen] = React.useState<
    null | 'details' | 'contract' | 'run' | 'runs' | 'ctxSettings'
  >(null)
  const [resultOpen, setResultOpen] = React.useState(false)
  const [activeRunId, setActiveRunId] = React.useState<number | null>(null)
  const [openedRunId, setOpenedRunId] = React.useState<number | null>(null)
  const [newRunId, setNewRunId] = React.useState<number | null>(null)
  const [graphScanStatus, setGraphScanStatus] = React.useState<string | null>(null)
  const [graphScanBusy, setGraphScanBusy] = React.useState(false)
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

  const [detailsOpen, setDetailsOpen] = React.useState<boolean>(() => {
    try { return (localStorage.getItem('cs.ui.detailsOpen') || '1') !== '0' } catch { return true }
  })
  React.useEffect(() => {
    try { localStorage.setItem('cs.ui.detailsOpen', detailsOpen ? '1' : '0') } catch {}
  }, [detailsOpen])

  const [runOpen, setRunOpen] = React.useState<boolean>(() => {
    try { return (localStorage.getItem('cs.ui.runOpen') || '1') !== '0' } catch { return true }
  })
  React.useEffect(() => {
    try { localStorage.setItem('cs.ui.runOpen', runOpen ? '1' : '0') } catch {}
  }, [runOpen])

  const [contractOpen, setContractOpen] = React.useState<boolean>(() => {
    try { return (localStorage.getItem('cs.ui.contractOpen') || '') === '1' } catch { return false }
  })
  React.useEffect(() => {
    try { localStorage.setItem('cs.ui.contractOpen', contractOpen ? '1' : '0') } catch {}
  }, [contractOpen])

  const [runsFilterQ, setRunsFilterQ] = React.useState('')
  const [runsFilterMode, setRunsFilterMode] = React.useState<'all' | Mode>('all')
  const [runsPage, setRunsPage] = React.useState(0)
  const [runsPageSize, setRunsPageSize] = React.useState(10)

  const isAuto = mode === 'auto'
  const isAgentic = retrievalMode === 'agentic'
  const patchAllowed = isAuto || mode === 'fix'
  const isRecord = (val: unknown): val is Record<string, unknown> => typeof val === 'object' && val !== null
  const graphScanTaskId = runResult?.graph_scan_task_id ?? null
  const graphScanWarning = runResult?.warning === 'graph not built'

  React.useEffect(() => {
    setGraphScanStatus(runResult?.graph_scan_status ?? null)
  }, [runResult?.graph_scan_status, runResult?.graph_scan_task_id])

  const refreshGraphScanStatus = React.useCallback(async () => {
    if (!graphScanTaskId) return
    setGraphScanBusy(true)
    try {
      const status = await getTaskStatus(graphScanTaskId)
      setGraphScanStatus(status.status ?? null)
    } catch {
      notifyInfo('Failed to update scan status')
    } finally {
      setGraphScanBusy(false)
    }
  }, [graphScanTaskId, notifyInfo])

  React.useEffect(() => {
    if (!resultOpen || !graphScanTaskId || !graphScanWarning) return
    if (graphScanStatus !== 'pending' && graphScanStatus !== 'running') return

    let active = true
    const intervalId = window.setInterval(async () => {
      if (!active) return
      try {
        const status = await getTaskStatus(graphScanTaskId)
        if (!active) return
        setGraphScanStatus(status.status ?? null)
      } catch {}
    }, 3000)

    return () => {
      active = false
      window.clearInterval(intervalId)
    }
  }, [graphScanStatus, graphScanTaskId, graphScanWarning, resultOpen])
  React.useEffect(() => {
    if (applyPatch && !patchAllowed) setApplyPatch(false)
  }, [applyPatch, patchAllowed, setApplyPatch])

  const [ctxAdvancedOpen, setCtxAdvancedOpen] = React.useState<boolean>(() => {
    try { return (localStorage.getItem('cs.ui.ctxAdvancedOpen') || '') === '1' } catch { return false }
  })
  React.useEffect(() => {
    try { localStorage.setItem('cs.ui.ctxAdvancedOpen', ctxAdvancedOpen ? '1' : '0') } catch {}
  }, [ctxAdvancedOpen])

  const clampFloat = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

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

  const runPayload = runResult ? (isRecord(runResult.result) ? runResult.result : { raw: runResult.result }) : null
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

  const fmtK = (n: unknown): string => {
    const v = Number(n)
    if (!Number.isFinite(v)) return '—'
    const abs = Math.abs(v)
    if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
    if (abs >= 1_000) return `${Math.round(v / 1_000)}k`
    return String(Math.round(v))
  }

  const fmtDuration = (n: unknown): string => {
    const v = Number(n)
    if (!Number.isFinite(v)) return '—'
    if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(2)}s`
    return `${Math.round(v)}ms`
  }

  const fmtTraceArgs = (args: unknown): string => {
    if (args == null) return '—'
    let raw = ''
    if (typeof args === 'string') {
      raw = args
    } else {
      try {
        raw = JSON.stringify(args)
      } catch {
        raw = String(args)
      }
    }
    if (!raw) return '—'
    const maxLen = 240
    return raw.length > maxLen ? `${raw.slice(0, maxLen)}…` : raw
  }

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

  const asStringList = (value: unknown): string[] => {
    if (!Array.isArray(value)) return []
    return value
      .map((item) => (typeof item === 'string' ? item.trim() : ''))
      .filter(Boolean)
  }

  const inlineTokenRegex =
    /([A-Za-z0-9._-]*\/[A-Za-z0-9._/-]*\.[A-Za-z0-9]+|\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+\b|\b[A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]*\b)/

  const renderInlineHighlights = (children: React.ReactNode) =>
    React.Children.map(children, (child, index) => {
      if (typeof child !== 'string') return child
      const parts = child.split(inlineTokenRegex)
      return parts.map((part, partIndex) => {
        if (!part) return null
        if (!inlineTokenRegex.test(part)) {
          return <React.Fragment key={`${index}-${partIndex}`}>{part}</React.Fragment>
        }
        return (
          <span
            key={`${index}-${partIndex}`}
            className="font-mono text-[11px] rounded border border-neutral-700 bg-neutral-950 px-1 py-0.5 text-indigo-100 shadow-inner shadow-black/40"
          >
            {part}
          </span>
        )
      })
    })

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

  const promptChips = useMemo(() => {
    return [
      { label: 'Explain', mode: 'analyze' as const, text: 'Explain the file purpose. Point out key functions/classes and responsibilities.' },
      { label: 'Risks', mode: 'analyze' as const, text: 'Find major risks/bottlenecks: complexity, dependencies, potential bugs. Provide recommendations.' },
      { label: 'Refactor plan', mode: 'evolve' as const, text: 'Propose a refactor plan: steps, what to touch, risks, and how to validate with tests.' },
      { label: 'Add tests', mode: 'evolve' as const, text: 'Propose a set of tests (unit/integration) for key logic, including edge cases.' },
      { label: 'Fix', mode: 'fix' as const, text: 'Fix the issue: <description>. Preserve behavior/contract. Add/update tests. Return a patch.' },
      { label: 'Impact', mode: 'impact' as const, text: 'If we change <symbol/behavior>, which files are affected? Return a list and brief reasons.' },
    ]
  }, [])

  const filteredRuns = useMemo(() => {
    const q = runsFilterQ.trim().toLowerCase()
    return (runs || [])
      .filter((r) => {
        if (!q) return true
        const hay = `${r.target_path ?? ''} ${r.prompt ?? ''} ${r.mode ?? ''}`.toLowerCase()
        return hay.includes(q)
      })
      .filter((r) => (runsFilterMode === 'all' ? true : r.mode === runsFilterMode))
      .slice(0, 50)
  }, [runs, runsFilterMode, runsFilterQ])

  React.useEffect(() => {
    setRunsPage(0)
  }, [runsFilterMode, runsFilterQ, runsPageSize])

  const runsTotalPages = Math.max(1, Math.ceil(filteredRuns.length / runsPageSize))
  React.useEffect(() => {
    if (runsPage > runsTotalPages - 1) {
      setRunsPage(Math.max(0, runsTotalPages - 1))
    }
  }, [runsPage, runsTotalPages])

  const pagedRuns = useMemo(() => {
    const start = runsPage * runsPageSize
    return filteredRuns.slice(start, start + runsPageSize)
  }, [filteredRuns, runsPage, runsPageSize])

  const HelpButton = ({
    topic,
    label,
  }: {
    topic: 'details' | 'contract' | 'run' | 'runs' | 'ctxSettings'
    label?: string
  }) => (
    <button
      type="button"
      className="w-3.5 h-3.5 rounded-full border border-neutral-800 bg-neutral-900 text-neutral-200 text-[10px] leading-none font-semibold hover:bg-neutral-800 shrink-0"
      onMouseDown={(e) => { e.preventDefault(); e.stopPropagation() }}
      onClick={() => setHelpOpen(topic)}
      aria-label={label || 'Open help'}
      title={label || 'Help'}
    >
      ?
    </button>
  )

  const controlBase = 'w-full h-9 rounded-md bg-neutral-900 border border-neutral-800 px-2 text-xs outline-none'
  const controlDisabled = 'disabled:opacity-50'
  const controlClass = `${controlBase} ${controlDisabled}`
  const labelRowClass = 'flex items-center gap-2 leading-none'
  const fieldLabelClass = 'text-[11px] font-semibold text-neutral-200'

  const chipBase = 'h-6 px-2 rounded-full border text-[10px] font-semibold transition-colors disabled:opacity-50'
  const chipIdle = 'bg-neutral-900 border-neutral-800 hover:bg-neutral-800'
  const chipActive = 'bg-indigo-950/40 border-indigo-700'

  const showRunFooter = Boolean(selectedPath && runOpen)
  const isActiveRunLoaded = activeRunId == null || runResult?.run_id === activeRunId

  React.useEffect(() => {
    if (!runResult?.run_id) return
    if (openedRunId !== runResult.run_id) setNewRunId(runResult.run_id)
  }, [openedRunId, runResult?.run_id])

  const ToggleBtn = ({
    open,
    onClick,
    title,
  }: {
    open: boolean
    onClick: () => void
    title: string
  }) => (
    <button
      type="button"
      className="h-6 rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2.5 text-[11px] font-semibold"
      onClick={onClick}
      title={title}
    >
      {open ? 'Hide' : 'Show'}
    </button>
  )

  const SectionHeader = ({
    title,
    topic,
    open,
    onToggle,
    toggleTitle,
    actions,
  }: {
    title: string
    topic: 'details' | 'contract' | 'run' | 'runs' | 'ctxSettings'
    open?: boolean
    onToggle?: () => void
    toggleTitle?: string
    actions?: React.ReactNode
  }) => (
    <div className="flex items-center justify-between gap-3 min-h-6">
      <div className="flex items-center gap-2">
        <div className="text-sm font-semibold text-neutral-200 leading-none">{title}</div>
        <HelpButton topic={topic} label={`Help: ${title}`} />
      </div>
      <div className="flex items-center gap-2">
        {actions}
        {typeof open === 'boolean' && onToggle ? (
          <ToggleBtn open={open} onClick={onToggle} title={toggleTitle || `${open ? 'Hide' : 'Show'} ${title}`} />
        ) : null}
      </div>
    </div>
  )

  const resultText = useMemo(
    () => formatResult(runPayload as Record<string, any> | null),
    [runPayload],
  )
  const resultMarkdownComponents = useMemo<Components>(() => ({
    h1: ({ node, className, ...props }) => (
      <h1
        {...props}
        className={['text-sm font-semibold text-neutral-100 mt-1 mb-2', className].filter(Boolean).join(' ')}
      />
    ),
    h2: ({ node, className, ...props }) => (
      <h2
        {...props}
        className={['text-xs font-semibold text-neutral-100 mt-4 mb-2', className].filter(Boolean).join(' ')}
      />
    ),
    h3: ({ node, className, ...props }) => (
      <h3
        {...props}
        className={['text-[11px] font-semibold text-neutral-100 mt-3 mb-2', className].filter(Boolean).join(' ')}
      />
    ),
    p: ({ node, className, children, ...props }) => (
      <p
        {...props}
        className={['text-xs text-neutral-200 leading-relaxed my-2', className].filter(Boolean).join(' ')}
      >
        {renderInlineHighlights(children)}
      </p>
    ),
    ul: ({ node, className, ...props }) => (
      <ul {...props} className={['list-disc pl-5 my-2 space-y-1', className].filter(Boolean).join(' ')} />
    ),
    ol: ({ node, className, ...props }) => (
      <ol {...props} className={['list-decimal pl-5 my-2 space-y-1', className].filter(Boolean).join(' ')} />
    ),
    li: ({ node, className, children, ...props }) => (
      <li {...props} className={['text-xs text-neutral-200', className].filter(Boolean).join(' ')}>
        {renderInlineHighlights(children)}
      </li>
    ),
    pre: ({ node, className, ...props }) => (
      <pre
        {...props}
        className={['text-xs bg-neutral-950 border border-neutral-800 rounded-md p-2 overflow-auto my-2', className]
          .filter(Boolean)
          .join(' ')}
      />
    ),
    table: ({ node, className, ...props }) => (
      <div className="my-3 overflow-auto">
        <table {...props} className={['w-full text-xs border-collapse', className].filter(Boolean).join(' ')} />
      </div>
    ),
    thead: ({ node, className, ...props }) => (
      <thead {...props} className={['bg-neutral-900/40', className].filter(Boolean).join(' ')} />
    ),
    th: ({ node, className, children, ...props }) => (
      <th
        {...props}
        className={['border border-neutral-800 px-2 py-1 text-left text-neutral-200 font-semibold align-top', className]
          .filter(Boolean)
          .join(' ')}
      >
        {renderInlineHighlights(children)}
      </th>
    ),
    td: ({ node, className, children, ...props }) => (
      <td
        {...props}
        className={['border border-neutral-800 px-2 py-1 text-neutral-200 align-top', className]
          .filter(Boolean)
          .join(' ')}
      >
        {renderInlineHighlights(children)}
      </td>
    ),
    code: ({ node, className, children, ...props }) => {
      const isInline = !(className && /\blanguage-/.test(className))

      if (isInline) {
        return (
          <code
            {...props}
            className={[
              'font-mono text-[11px] rounded border border-neutral-700 bg-neutral-950 px-1 py-0.5 text-indigo-100 shadow-inner shadow-black/40',
              className || '',
            ].join(' ')}
          >
            {children}
          </code>
        )
      }

      return (
        <code {...props} className={['font-mono text-[11px]', className || ''].join(' ')}>
          {children}
        </code>
      )
    },
    a: ({ node, className, ...props }) => (
      <a
        {...props}
        className={['text-indigo-300 font-semibold underline decoration-indigo-500/60 hover:text-indigo-200', className]
          .filter(Boolean)
          .join(' ')}
        target={props.target ?? '_blank'}
        rel={props.rel ?? 'noreferrer'}
      />
    ),
  }), [renderInlineHighlights])

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
                    <LanguageIcon language={nodeInfo.language} className="h-3 w-3" />
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
                      LANG: <LanguageIcon language={nodeInfo.language} className="h-3.5 w-3.5" />
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
                          Graph index is incomplete. For correct context, run a full Scan — otherwise LLM/impact results may be incomplete.
                        </div>
                        <button
                          type="button"
                          className="rounded-md bg-amber-900/40 hover:bg-amber-900/60 border border-amber-800 px-3 py-1 text-[11px] font-semibold disabled:opacity-50"
                          onClick={() => onScan()}
                          disabled={!activeProject || busy}
                        >
                          Scan
                        </button>
                      </div>
                    )}
                    <div className="mt-2">
                      <div className={labelRowClass}>
                        <span className={fieldLabelClass}>Prompt</span>
                      </div>
                      <textarea
                        ref={promptRef}
                        className="mt-1 w-full rounded-md bg-neutral-900 border border-neutral-800 px-3 py-2 text-xs min-h-[110px] placeholder:text-neutral-600 disabled:opacity-50"
                        value={prompt}
                        onChange={(e) => setPrompt(e.target.value)}
                        disabled={busy}
                        placeholder={promptPlaceholder}
                      />
                    </div>

                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {promptChips.map((c) => (
                        <button
                          key={c.label}
                          type="button"
                          className={[chipBase, prompt.trim() === c.text.trim() ? chipActive : chipIdle].join(' ')}
                          onClick={() => {
                            setMode(c.mode)
                            setPrompt(c.text)
                            try {
                              window.setTimeout(() => {
                                promptRef.current?.focus?.()
                              }, 0)
                            } catch {}
                          }}
                          disabled={busy}
                          title="Insert template"
                        >
                          {c.label}
                        </button>
                      ))}
                    </div>

                    <div className="mt-2">
                      <SectionHeader
                        title="Context Settings"
                        topic="ctxSettings"
                        open={ctxAdvancedOpen}
                        onToggle={() => setCtxAdvancedOpen((v) => !v)}
                        toggleTitle="Show/hide context settings"
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
                  </>
                )}
              </div>

              <div className="mt-4">
                <SectionHeader
                  title="Runs"
                  topic="runs"
                  actions={(
                    <div className="flex flex-wrap items-center gap-2 text-[11px] text-neutral-400">
                      <span>{filteredRuns.length} total</span>
                      <label className="flex items-center gap-1 text-[11px] text-neutral-400">
                        <span>Per page</span>
                        <select
                          className="h-6 rounded-md bg-neutral-900 border border-neutral-800 px-1.5 text-[11px] text-neutral-200"
                          value={runsPageSize}
                          onChange={(e) => setRunsPageSize(clampInt(Number(e.target.value || 10), 5, 50))}
                        >
                          <option value={5}>5</option>
                          <option value={10}>10</option>
                          <option value={20}>20</option>
                          <option value={50}>50</option>
                        </select>
                      </label>
                      <span>
                        Page {Math.min(runsPage + 1, runsTotalPages)}/{runsTotalPages}
                      </span>
                      <button
                        type="button"
                        className="h-6 rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 font-semibold disabled:opacity-50"
                        onClick={() => setRunsPage(0)}
                        disabled={runsPage <= 0}
                        title="First page"
                      >
                        First
                      </button>
                      <button
                        type="button"
                        className="h-6 rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 font-semibold disabled:opacity-50"
                        onClick={() => setRunsPage((p) => Math.max(0, p - 1))}
                        disabled={runsPage <= 0}
                        title="Previous page"
                      >
                        Prev
                      </button>
                      <button
                        type="button"
                        className="h-6 rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 font-semibold disabled:opacity-50"
                        onClick={() => setRunsPage((p) => Math.min(runsTotalPages - 1, p + 1))}
                        disabled={runsPage >= runsTotalPages - 1}
                        title="Next page"
                      >
                        Next
                      </button>
                      <button
                        type="button"
                        className="h-6 rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 font-semibold disabled:opacity-50"
                        onClick={() => setRunsPage(runsTotalPages - 1)}
                        disabled={runsPage >= runsTotalPages - 1}
                        title="Last page"
                      >
                        Last
                      </button>
                    </div>
                  )}
                />
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <input
                    className="w-full rounded-md bg-neutral-900 border border-neutral-800 px-2 py-1 text-xs"
                    placeholder="filter (path/prompt)…"
                    value={runsFilterQ}
                    onChange={(e) => setRunsFilterQ(e.target.value)}
                  />
                  <select
                    className="w-full rounded-md bg-neutral-900 border border-neutral-800 px-2 py-1 text-xs"
                    value={runsFilterMode}
                    onChange={(e) => setRunsFilterMode(e.target.value as any)}
                  >
                    <option value="all">All</option>
                    <option value="analyze">Analyze</option>
                    <option value="evolve">Evolve</option>
                    <option value="fix">Fix</option>
                    <option value="impact">Impact</option>
                  </select>
                </div>
                <div className="mt-2 flex flex-col gap-2">
                  {pagedRuns.length === 0 ? (
                    <div className="text-xs text-neutral-500">No runs found.</div>
                  ) : pagedRuns.map((r) => {
                    const key = r.id
                    const rid = r.id
                    const isNew = newRunId === rid
                    return (
                      <div
                        key={key}
                        className={[
                          'text-xs border rounded-md p-2 transition-colors',
                          isNew ? 'bg-indigo-500/5 border-indigo-500/60' : 'bg-neutral-950 border-neutral-800',
                        ].join(' ')}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <button
                            type="button"
                            className="min-w-0 flex-1 text-left hover:opacity-90 disabled:opacity-50"
                            onClick={() => onLoadRun(rid)}
                            disabled={busy || nodeBusy || patchBusy || runLoadBusy || !activeProject || !Number.isFinite(rid)}
                            title="Load this run"
                          >
                            <div className="text-neutral-200 font-semibold truncate">#{r.id} · {r.mode} · {r.target_path}</div>
                            <div className="text-neutral-500">{r.created_at}</div>
                            <div className="text-neutral-300 line-clamp-2">{r.prompt}</div>
                          </button>
                          <div className="shrink-0 flex flex-col gap-1">
                            <button
                              type="button"
                              className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold disabled:opacity-50"
                              onClick={async () => {
                                if (!Number.isFinite(rid)) return
                                setActiveRunId(rid)
                                setOpenedRunId(rid)
                                if (newRunId === rid) setNewRunId(null)
                                setResultOpen(true)
                                if (runResult?.run_id !== rid) {
                                  await onLoadRun(rid)
                                }
                              }}
                              disabled={busy || nodeBusy || patchBusy || runLoadBusy || !activeProject || !Number.isFinite(rid)}
                              title="Open result"
                            >
                              Open
                            </button>
                            <button
                              type="button"
                              className="rounded-md bg-red-900/40 hover:bg-red-900/60 border border-red-800 px-2 py-1 text-[11px] font-semibold text-red-100 disabled:opacity-50"
                              onClick={async () => {
                                if (!Number.isFinite(rid)) return
                                if (!window.confirm('Delete this run?')) return
                                if (activeRunId === rid) {
                                  setActiveRunId(null)
                                  setResultOpen(false)
                                }
                                if (newRunId === rid) setNewRunId(null)
                                await onDeleteRun(rid)
                              }}
                              disabled={busy || nodeBusy || patchBusy || runLoadBusy || !activeProject || !Number.isFinite(rid)}
                              title="Delete run"
                            >
                              Delete
                            </button>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
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

        <Modal
          open={resultOpen}
          title="Result"
          onClose={() => {
            setResultOpen(false)
            setActiveRunId(null)
          }}
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
                      Background Scan started to build the graph. Results may be incomplete until it finishes.
                    </div>
                    <div className="text-[11px] text-amber-300">
                      Status: {graphScanStatus ?? '—'}
                      {graphScanTaskId ? ` · task_id: ${graphScanTaskId}` : ''}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        className="rounded-md bg-amber-900/40 hover:bg-amber-900/60 border border-amber-800 px-3 py-1 text-[11px] font-semibold disabled:opacity-50"
                        onClick={refreshGraphScanStatus}
                        disabled={!graphScanTaskId || graphScanBusy}
                      >
                        {graphScanBusy ? 'Updating…' : 'Refresh status'}
                      </button>
                      <button
                        type="button"
                        className="rounded-md bg-amber-900/40 hover:bg-amber-900/60 border border-amber-800 px-3 py-1 text-[11px] font-semibold disabled:opacity-50"
                        onClick={() => onScan()}
                        disabled={!activeProject || busy}
                      >
                        Go to Scan
                      </button>
                    </div>
                  </div>
                )}
                {agenticTrace.length > 0 && (
                  <div className="mt-3">
                    <div className="text-xs font-semibold text-neutral-200">Tool trace</div>
                    <div className="mt-2 space-y-2">
                      {agenticTrace.map((entry, idx) => {
                        const status = String((entry as any).status || '—')
                        const ok = status === 'ok'
                        return (
                          <div
                            key={`${(entry as any).name ?? 'tool'}-${idx}`}
                            className="rounded-md border border-neutral-800 bg-neutral-950/60 px-2 py-2 text-xs"
                          >
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div className="font-mono text-[11px] text-indigo-200">
                                {(entry as any).name ?? '—'}
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
                      onClick={onRunWithExpandedContext}
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

        <Modal
          open={helpOpen != null}
          title={
            helpOpen === 'details'
              ? 'Help: Details'
            :
             helpOpen === 'contract'
              ? 'Help: Contract'
            : helpOpen === 'run'
              ? 'Help: Run task'
            : helpOpen === 'runs'
               ? 'Help: Results'
            : helpOpen === 'ctxSettings'
              ? 'Help: Context settings'
            : 'Help'
          }
          onClose={() => setHelpOpen(null)}
        >
          {helpOpen === 'details' && (
            <div className="space-y-2">
              <div className="text-neutral-200 font-semibold">Node metrics</div>
              <div>• <span className="font-mono">LOC</span> — lines of code (as counted by the backend).</div>
              <div>• <span className="font-mono">Fan In / Fan Out</span> — inbound/outbound dependencies in the graph.</div>
              <div>• <span className="font-mono">Complexity</span> — complexity estimate (method depends on the backend).</div>
              <div>• <span className="font-mono">SCC</span> — Strongly Connected Component: id of a cyclic dependency group.</div>
              <div>• <span className="font-mono">Status</span> — label/state from the backend (e.g. <span className="font-mono">new</span>). Exact values depend on the indexer.</div>
            </div>
          )}
          {helpOpen === 'contract' && (
            <div className="space-y-2">
              <div>• Contract — structured description of node API/behavior (what the file/module “promises”).</div>
              <div>• Used for faster/cheaper tasks (especially with dep_mode=contracts).</div>
              <div>• If the contract is empty/stale — run Scan/Refresh.</div>
            </div>
          )}
          {helpOpen === 'run' && (
            <div className="space-y-2">
              <div className="text-neutral-200 font-semibold">Run task: how to choose settings</div>
              <div>• Fill in <span className="font-mono">Prompt</span> and pick a preset if needed.</div>
              <div>• All context settings are now in <span className="font-mono">Context Settings</span> (can be collapsed/expanded).</div>
              <div>• By default <span className="font-mono">Apply patch</span> is off — enable it only if you need a diff.</div>
            </div>
          )}
          {helpOpen === 'runs' && (
            <div className="space-y-2">
              <div>• Results — history of completed tasks for the project/files.</div>
              <div>• New runs are highlighted until you open the result.</div>
              <div>• The <span className="font-mono">Open</span> button opens a modal with context and a patch.</div>
            </div>
          )}
          {helpOpen === 'ctxSettings' && (
            <div className="space-y-2">
              <div className="text-neutral-200 font-semibold">Context Settings</div>
              <div>• <span className="font-mono">Context</span>: Agentic — context via tools; Pack — bundled package via graph/contracts.</div>
              <div>• <span className="font-mono">Mode</span>: auto/analyze/evolve/fix/impact — response logic.</div>
              <div>• <span className="font-mono">Depth</span> and <span className="font-mono">Dependencies</span> control depth and dependency types.</div>
              <div>• <span className="font-mono">Apply patch</span> applies a unified diff (usually only for fix).</div>
              <div className="pt-2 text-neutral-200 font-semibold">Limits</div>
              <div>• These control context budget and action count.</div>
            </div>
          )}
        </Modal>
      </div>
    </div>
  )
}
