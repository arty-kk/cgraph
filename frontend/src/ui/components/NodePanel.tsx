// frontend/src/ui/components/NodePanel.tsx
import React, { useMemo } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { DepMode, Mode, NodeContract, NodeInfo, Project, RunRecord, RunTaskResult } from '../../api'
import { clampInt } from '../../lib/number'
import { formatResult } from '../../lib/formatResult'
import { Modal } from './Modal'

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
  setPackMaxFiles: (v: number) => void
  setPackMaxCharsPerFile: (v: number) => void
  setPackMaxTotalChars: (v: number) => void
  setApplyPatch: (v: boolean) => void
  setPrompt: (v: string) => void

  canRun: boolean
  onRun: () => void | Promise<void>

  runResult: RunTaskResult | null
  fullPatch: string | null
  patchBusy: boolean
  runLoadBusy: boolean
  onLoadFullPatch: () => void | Promise<void>
  onLoadRun: (runId: number) => void | Promise<void>
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
  setPackMaxFiles,
  setPackMaxCharsPerFile,
  setPackMaxTotalChars,
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

  const promptRef = React.useRef<HTMLTextAreaElement | null>(null)
  const [helpOpen, setHelpOpen] = React.useState<
    null | 'details' | 'contract' | 'run' | 'result' | 'runs' | 'context' | 'ctxSettings'
  >(null)
  const [resultOpen, setResultOpen] = React.useState(false)
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

  const isAuto = mode === 'auto'
  const isAgentic = retrievalMode === 'agentic'
  const patchAllowed = isAuto || mode === 'fix'
  const isRecord = (val: unknown): val is Record<string, unknown> => typeof val === 'object' && val !== null

  React.useEffect(() => {
    if (applyPatch && !patchAllowed) setApplyPatch(false)
  }, [applyPatch, patchAllowed, setApplyPatch])

  const coerceAutoOrMode = (m: unknown): AutoOrMode => {
    const s = String(m ?? '').trim()
    return s === 'analyze' || s === 'evolve' || s === 'fix' || s === 'impact' ? (s as any) : 'auto'
  }

  const [ctxAdvancedOpen, setCtxAdvancedOpen] = React.useState<boolean>(() => {
    try { return (localStorage.getItem('cs.ui.ctxAdvancedOpen') || '') === '1' } catch { return false }
  })
  React.useEffect(() => {
    try { localStorage.setItem('cs.ui.ctxAdvancedOpen', ctxAdvancedOpen ? '1' : '0') } catch {}
  }, [ctxAdvancedOpen])

  const clampFloat = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

  const promptPlaceholder =
    isAuto
      ? 'Опиши задачу для выбранного файла. Примеры: "объясни назначение и риски", "предложи рефакторинг", "исправь баг и добавь тест", "покажи impact изменения X".'
      : mode === 'analyze'
        ? 'Пример: "Кратко опиши назначение файла, найди точки риска/узкие места и предложи улучшения".'
        : mode === 'evolve'
          ? 'Пример: "Предложи безопасный план улучшений/рефакторинга: шаги, затронутые места, тесты".'
          : mode === 'fix'
            ? 'Пример: "Исправь <описание проблемы>, не ломая контракт; добавь/обнови тест(ы). Верни патч".'
            : mode === 'impact'
              ? 'Пример: "Если изменить <символ/поведение>, какие файлы/модули будут затронуты?"'
              : 'Опиши задачу.'

  const runPayload = runResult ? (isRecord(runResult.result) ? runResult.result : { raw: runResult.result }) : null

  const retrieval = (runResult as any)?.retrieval ?? runResult?.retrieval ?? '—'
  const retrievalSettings = (runResult as any)?.retrieval_settings ?? runResult?.retrieval_settings

  const fmtK = (n: unknown): string => {
    const v = Number(n)
    if (!Number.isFinite(v)) return '—'
    const abs = Math.abs(v)
    if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
    if (abs >= 1_000) return `${Math.round(v / 1_000)}k`
    return String(Math.round(v))
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
      { label: 'Explain', mode: 'analyze' as const, text: 'Объясни назначение файла. Укажи ключевые функции/классы и ответственность.' },
      { label: 'Risks', mode: 'analyze' as const, text: 'Найди основные риски/узкие места: сложность, зависимости, потенциальные баги. Дай рекомендации.' },
      { label: 'Refactor plan', mode: 'evolve' as const, text: 'Предложи план рефакторинга: шаги, что затронуть, риски, как проверить тестами.' },
      { label: 'Add tests', mode: 'evolve' as const, text: 'Предложи набор тестов (unit/integration) для ключевой логики, включая edge cases.' },
      { label: 'Fix', mode: 'fix' as const, text: 'Исправь проблему: <описание>. Сохрани поведение/контракт. Добавь/обнови тесты. Верни патч.' },
      { label: 'Impact', mode: 'impact' as const, text: 'Если изменить <символ/поведение>, какие файлы будут затронуты? Верни список и краткие причины.' },
    ]
  }, [])

  const filteredRuns = useMemo(() => {
    const q = runsFilterQ.trim().toLowerCase()
    return (runs || [])
      .filter((r) => (runsFilterMode === 'all' ? true : r.mode === runsFilterMode))
      .filter((r) => {
        if (!q) return true
        const hay = `${r.target_path ?? ''} ${r.prompt ?? ''} ${r.mode ?? ''}`.toLowerCase()
        return hay.includes(q)
      })
      .slice(0, 50)
  }, [runs, runsFilterMode, runsFilterQ])

  const HelpButton = ({
    topic,
    label,
  }: {
    topic: 'details' | 'contract' | 'run' | 'result' | 'runs' | 'context' | 'ctxSettings'
    label?: string
  }) => (
    <button
      type="button"
      className="w-3.5 h-3.5 rounded-full border border-neutral-800 bg-neutral-900 text-neutral-200 text-[10px] leading-none font-semibold hover:bg-neutral-800 shrink-0"
      onMouseDown={(e) => { e.preventDefault(); e.stopPropagation() }}
      onClick={() => setHelpOpen(topic)}
      aria-label={label || 'Открыть подсказку'}
      title={label || 'Подсказка'}
    >
      ?
    </button>
  )

  const controlBase = 'w-full h-9 rounded-md bg-neutral-900 border border-neutral-800 px-2 text-xs outline-none'
  const controlDisabled = 'disabled:opacity-50'
  const controlClass = `${controlBase} ${controlDisabled}`
  const labelRowClass = 'flex items-center gap-2 leading-none'
  const fieldLabelClass = 'text-[11px] font-semibold text-neutral-200'

  const chipBase = 'h-8 px-3 rounded-full border text-[11px] font-semibold transition-colors disabled:opacity-50'
  const chipIdle = 'bg-neutral-900 border-neutral-800 hover:bg-neutral-800'
  const chipActive = 'bg-indigo-950/40 border-indigo-700'

  const showRunFooter = Boolean(selectedPath && runOpen)

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
    topic: 'details' | 'contract' | 'run' | 'result' | 'runs' | 'context' | 'ctxSettings'
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
            <div className="text-sm text-neutral-300">Выбери файл через поиск или клик по графу.</div>
          ) : (
            <>
              <div className="text-sm font-semibold truncate" title={selectedPath}>{selectedPath}</div>
              
              {!detailsOpen && nodeInfo && (
                <div className="mt-1 text-[11px] text-neutral-500">
                  {String(nodeInfo.language || '—')} · loc {Number.isFinite(Number(nodeInfo.loc)) ? Number(nodeInfo.loc) : '—'} · in {Number(nodeInfo.fan_in ?? 0)} · out {Number(nodeInfo.fan_out ?? 0)}
                </div>
              )}

              {detailsOpen && !selectedInGraph && graphTruncated && (
                <div className="mt-2 text-xs bg-neutral-950 border border-neutral-800 rounded-md p-2">
                  <div className="text-neutral-300">
                    Этот файл не попал в текущий граф (graph limited / top-N). Это не ошибка файла.
                  </div>
                  <button
                    className="mt-2 rounded-md bg-neutral-800 hover:bg-neutral-700 px-3 py-2 text-xs font-semibold disabled:opacity-50"
                    onClick={() => onLoadFullGraph()}
                    disabled={!activeProject}
                    title="Загрузить полный граф"
                  >
                    Загрузить полный граф
                  </button>
                </div>
              )}

              {detailsOpen && !nodeBusy && selectedPath && !selectedInGraph && !graphTruncated && (
                <div className="mt-2 text-xs text-amber-300 whitespace-pre-wrap">
                  Файл отсутствует в графе (возможно удалён/переименован или ещё не проиндексирован).
                  {'\n'}
                  Нажми Scan или Refresh.
                </div>
              )}

              {detailsOpen && nodeBusy ? (
                <div className="mt-2 text-xs text-neutral-400">Loading node…</div>
              ) : detailsOpen ? (
                nodeInfo && (
                  <div className="mt-2 text-xs text-neutral-300 grid grid-cols-2 gap-2">
                    <div>
                      LANG: <span className="text-neutral-100">{nodeInfo.language}</span>
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
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {promptChips.map((c) => (
                      <button
                        key={c.label}
                        type="button"
                        className={[chipBase, prompt.trim() === c.text.trim() ? chipActive : chipIdle].join(' ')}
                        onClick={() => {
                          setMode(c.mode)
                          setApplyPatch(c.mode === 'fix')
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

                  <div className="mt-2 grid grid-cols-2 gap-2">
                    <div className="text-xs text-neutral-300">
                      <div className="flex items-center gap-2 leading-none">
                        <span className="text-xs font-semibold text-neutral-200">Context</span>
                        <HelpButton topic="context" label="Help: Context" />
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
                        title="Auto — выбрать режим автоматически. Analyze — разбор/диагностика. Evolve — план улучшений. Fix — исправление (возможен patch). Impact — что затронет изменение."
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
                        title="Глубина захвата зависимостей для режима (кроме Auto). 0 — только файл, выше — глубже по графу."
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
                        title={isAgentic ? 'В agentic режиме dep_mode не используется' : 'dep_mode для pack_context'}
                      >
                        <option value="contracts">Contracts</option>
                        <option value="full">Full</option>
                      </select>
                    </div>

                    <label
                      className="col-span-2 h-9 rounded-md bg-neutral-900 border border-neutral-800 px-2 flex items-center justify-between gap-2"
                      title="Если включено — применить Unified Diff к репозиторию (имеет смысл в основном для Fix)."
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
                </div>

                <div className="mt-2">
                  <SectionHeader
                    title="Context Settings"
                    topic="ctxSettings"
                    open={ctxAdvancedOpen}
                    onToggle={() => setCtxAdvancedOpen((v) => !v)}
                    toggleTitle="Show/hide advanced context settings"
                  />

                  {ctxAdvancedOpen && (
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
                              min={200}
                              max={50000}
                              onChange={(e) => setAgenticMaxFileChars(clampInt(Number(e.target.value || 0), 200, 50000))}
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
                              min={2000}
                              max={1000000}
                              onChange={(e) => setAgenticMaxTotalToolOutputChars(clampInt(Number(e.target.value || 0), 2000, 1000000))}
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
                              min={200}
                              max={50000}
                              onChange={(e) => setPackMaxCharsPerFile(clampInt(Number(e.target.value || 0), 200, 50000))}
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
                              min={1000}
                              max={500000}
                              onChange={(e) => setPackMaxTotalChars(clampInt(Number(e.target.value || 0), 1000, 500000))}
                              disabled={busy}
                            />
                          </label>
                        </>
                      )}
                    </div>
                  )}
                </div>

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
                </>
              )}
            </div>

                <div className="mt-4">
                  <SectionHeader
                    title="Result"
                    topic="result"
                    actions={
                      runResult ? (
                        <button
                          type="button"
                          className="h-6 rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2.5 text-[11px] font-semibold"
                          onClick={() => setResultOpen(true)}
                          title="Open result in a separate window"
                        >
                          Open
                        </button>
                      ) : null
                    }
                  />
                {!runResult ? (
                  <div className="mt-2 text-xs text-neutral-400">—</div>
                ) : (
                  <div className="mt-2 space-y-3">
                    <div className="text-xs text-neutral-400">
                      run_id: {runResult?.run_id ?? '—'} · mode: {runResult?.mode ?? '—'} · depth:{' '}
                      {runResult?.depth ?? '—'} · dep_mode: {runResult?.dep_mode ?? '—'} · retrieval:{' '}
                      {String(retrieval)}
                    </div>
                    {retrievalSummary && (
                      <div className="text-[11px] text-neutral-500 whitespace-pre-wrap">{retrievalSummary}</div>
                    )}

                    {runResult?.applied?.error && (
                      <div className="text-xs text-red-300 whitespace-pre-wrap">
                        Patch Apply Error: {runResult.applied.error}
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

                    <div className="bg-neutral-900 border border-neutral-800 rounded-md p-3 text-xs text-neutral-200 leading-relaxed">
                      <ReactMarkdown remarkPlugins={[remarkGfm]} components={resultMarkdownComponents}>
                        {resultText}
                      </ReactMarkdown>
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

                        if (!hasPatch && !hasMeta) return null

                        const metaChars =
                          hasMeta && Number.isFinite(Number((patchMeta as any)?.chars))
                            ? Number((patchMeta as any).chars)
                            : null

                        return (
                          <>
                            <div className="flex items-center justify-between gap-2 text-xs font-semibold text-neutral-200">
                              <div>Patch (Unified Diff)</div>
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
                                Copy patch
                              </button>
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
                  </div>
                )}
              </div>

              <div className="mt-6">
                <SectionHeader title="Recent Runs" topic="runs" />
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
                  {filteredRuns.slice(0, 10).map((r) => {
                    const key = r.id
                    const rid = r.id
                    return (
                      <div key={key} className="text-xs bg-neutral-950 border border-neutral-800 rounded-md p-2">
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
                              className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
                              onClick={() => handleCopy(String(r.prompt ?? ''), 'Prompt copied')}
                              title="Copy prompt"
                            >
                              Copy
                            </button>
                            <button
                              type="button"
                              className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
                              onClick={() => {
                                const nextMode = coerceAutoOrMode(r.mode)
                                setMode(nextMode)
                                setApplyPatch(nextMode === 'fix')
                                setPrompt(String(r.prompt ?? ''))
                                try {
                                  window.setTimeout(() => {
                                    promptRef.current?.focus?.()
                                  }, 0)
                                } catch {}
                              }}
                              title="Use this prompt/mode"
                            >
                              Use
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
          open={resultOpen && !!runResult}
          title="Result"
          onClose={() => setResultOpen(false)}
        >
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className="rounded-md bg-neutral-800 hover:bg-neutral-700 px-3 py-2 text-xs font-semibold disabled:opacity-50"
                  onClick={async () => {
                    if (!resultText.trim()) return
                    await handleCopy(resultText, 'Result copied')
                  }}
                  disabled={!resultText.trim()}
                >
                Copy result
              </button>
            </div>
            <div className="text-xs text-neutral-500">
              {runResult?.run_id ? `run_id: ${runResult.run_id}` : 'Result preview'}
            </div>
            <div className="text-xs bg-neutral-950 border border-neutral-800 rounded-md p-3 overflow-auto max-h-[70vh]">
              {!resultText.trim() ? (
                <div className="text-neutral-500">—</div>
              ) : (
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={resultMarkdownComponents}>
                  {resultText}
                </ReactMarkdown>
              )}
            </div>
          </div>
        </Modal>

        <Modal
          open={helpOpen != null}
           title={
            helpOpen === 'details'
              ? 'Подсказка: Details'
            :
             helpOpen === 'contract'
              ? 'Подсказка: Contract'
            : helpOpen === 'run'
              ? 'Подсказка: Run task'
            : helpOpen === 'result'
              ? 'Подсказка: Result'
            : helpOpen === 'runs'
               ? 'Подсказка: Recent runs'
            : helpOpen === 'context'
              ? 'Подсказка: Context'
            : helpOpen === 'ctxSettings'
              ? 'Подсказка: Context settings'
            : 'Подсказка'
          }
          onClose={() => setHelpOpen(null)}
        >
          {helpOpen === 'details' && (
            <div className="space-y-2">
              <div className="text-neutral-200 font-semibold">Метрики узла</div>
              <div>• <span className="font-mono">LOC</span> — строки кода (как считает backend).</div>
              <div>• <span className="font-mono">Fan In / Fan Out</span> — входящие/исходящие зависимости по графу.</div>
              <div>• <span className="font-mono">Complexity</span> — оценка сложности (методика зависит от backend).</div>
              <div>• <span className="font-mono">SCC</span> — Strongly Connected Component: идентификатор группы циклических зависимостей.</div>
              <div>• <span className="font-mono">Status</span> — метка/состояние узла от backend (напр. <span className="font-mono">new</span>). Точные значения зависят от индексатора.</div>
            </div>
          )}
          {helpOpen === 'contract' && (
            <div className="space-y-2">
              <div>• Contract — структурированное описание API/поведения узла (что “обещает” файл/модуль).</div>
              <div>• Используется для более быстрых/дешёвых задач (особенно при dep_mode=contracts).</div>
              <div>• Если контракт пустой/устарел — сделай Scan/Refresh.</div>
            </div>
          )}
          {helpOpen === 'run' && (
            <div className="space-y-2">
              <div className="text-neutral-200 font-semibold">Run task: как выбрать настройки</div>
              <div>• <span className="font-mono">Context</span>:</div>
              <div className="ml-3">— <span className="font-mono">Agentic</span>: модель сама добирает контекст через tools (чтение файлов/поиск) в пределах лимитов.</div>
              <div className="ml-3">— <span className="font-mono">Pack Context</span>: контекст собирается заранее по графу/контрактам в рамках бюджетов.</div>
              <div>• Mode:</div>
              <div className="ml-3">— auto: выбрать режим автоматически</div>
              <div className="ml-3">— analyze: разбор/диагностика</div>
              <div className="ml-3">— evolve: улучшение/рефакторинг/планы</div>
              <div className="ml-3">— fix: попытка исправления + (опционально) патч</div>
              <div className="ml-3">— impact: список затронутых файлов</div>
              <div>• Depth — насколько глубоко захватывать зависимости (если не auto).</div>
              <div>• Deps:</div>
              <div className="ml-3">— contracts: тянуть только контракты зависимостей</div>
              <div className="ml-3">— full: тянуть полный код зависимостей (дороже)</div>
              <div>• Apply patch — применить unified diff (обычно имеет смысл для fix).</div>
            </div>
          )}
          {helpOpen === 'result' && (
            <div className="space-y-2">
              <div>• Result — отформатированный ответ задачи (summary/diagnosis/risks/plan/tests и т.д.).</div>
              <div>• Patch (unified diff):</div>
              <div className="ml-3">— если патч большой, он может быть “omitted” и грузится кнопкой Load full patch.</div>
              <div>• Если Apply patch включён — ниже появится статус применения (modified/error).</div>
            </div>
          )}
          {helpOpen === 'runs' && (
            <div className="space-y-2">
              <div>• Recent runs — история запусков по проекту/файлам.</div>
              <div>• Клик по записи загрузит сохранённый результат и переключит выделение на target_path.</div>
              <div>• Удобно для сравнения “до/после” и отката к предыдущим выводам.</div>
            </div>
          )}
          {helpOpen === 'context' && (
            <div className="space-y-2">
              <div className="text-neutral-200 font-semibold">Что такое Context</div>
              <div>• <span className="font-mono">Agentic</span>: модель сама добирает нужный контекст через tools (чтение файлов/поиск) в пределах лимитов.</div>
              <div>• <span className="font-mono">Pack Context</span>: контекст собирается заранее по графу/контрактам/кодовой базе в рамках бюджетов.</div>
              <div className="text-neutral-400 text-[12px]">
                Практика: Agentic — гибче и часто точнее на сложных задачах. Pack — более предсказуем по объёму/стоимости и легче воспроизводится.
              </div>
            </div>
          )}
          {helpOpen === 'ctxSettings' && (
            <div className="space-y-2">
              <div className="text-neutral-200 font-semibold">Зачем нужны лимиты</div>
              <div>• Лимиты не “ухудшают” модель сами по себе — они управляют бюджетом контекста и количеством действий.</div>
              <div>• Слишком маленькие лимиты → недобор контекста. Слишком большие → лишние чтения/раздувание контекста.</div>
              <div className="pt-2 text-neutral-200 font-semibold">Agentic</div>
              <div>• <span className="font-mono">Max Calls</span>: максимум tool-вызовов на задачу.</div>
              <div>• <span className="font-mono">Max File Chars</span>: сколько символов можно прочитать из одного файла.</div>
              <div>• <span className="font-mono">Max Tool Output Chars</span>: суммарный бюджет вывода tools (чтобы не раздувать контекст).</div>
              <div>• <span className="font-mono">Temperature</span>: вариативность ответа (0 — максимально детерминированно).</div>
              <div className="pt-2 text-neutral-200 font-semibold">Pack Context</div>
              <div>• <span className="font-mono">Max Files</span>: максимум файлов в паке.</div>
              <div>• <span className="font-mono">Max Chars/File</span>: бюджет на каждый файл.</div>
              <div>• <span className="font-mono">Max Total Chars</span>: суммарный бюджет контекста.</div>
            </div>
          )}
        </Modal>
      </div>
    </div>
  )
}
