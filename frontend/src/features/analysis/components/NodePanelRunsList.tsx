import React, { useMemo } from 'react'
import type { Mode, Project, RunRecord, RunTaskResult } from '@/api'
import { clampInt } from '@/shared/lib/number'
import { SectionHeader, type HelpTopic } from './NodePanel.sections'

type Props = {
  runs: RunRecord[]
  activeProject: Project | null
  busy: boolean
  nodeBusy: boolean
  patchBusy: boolean
  runLoadBusy: boolean
  runResult: RunTaskResult | null
  activeRunId: number | null
  newRunId: number | null
  onLoadRun: (runId: number) => void | Promise<void>
  onDeleteRun: (runId: number) => void | Promise<void>
  onOpenHelp: (topic: HelpTopic) => void
  setActiveRunId: React.Dispatch<React.SetStateAction<number | null>>
  setNewRunId: React.Dispatch<React.SetStateAction<number | null>>
  setOpenedRunId: React.Dispatch<React.SetStateAction<number | null>>
  setResultOpen: React.Dispatch<React.SetStateAction<boolean>>
}

export function NodePanelRunsList({
  runs,
  activeProject,
  busy,
  nodeBusy,
  patchBusy,
  runLoadBusy,
  runResult,
  activeRunId,
  newRunId,
  onLoadRun,
  onDeleteRun,
  onOpenHelp,
  setActiveRunId,
  setNewRunId,
  setOpenedRunId,
  setResultOpen,
}: Props) {
  const [runsFilterQ, setRunsFilterQ] = React.useState('')
  const [runsFilterMode, setRunsFilterMode] = React.useState<'all' | Mode>('all')
  const [runsPage, setRunsPage] = React.useState(0)
  const [runsPageSize, setRunsPageSize] = React.useState(10)

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

  return (
    <div className="mt-4">
      <SectionHeader
        onOpenHelp={onOpenHelp}
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
  )
}
