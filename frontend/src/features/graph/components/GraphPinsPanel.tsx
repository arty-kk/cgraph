import React from 'react'
import type { GraphData } from '@/api'
import { baseName } from '../lib/GraphCanvas.helpers'
import { ClearIcon } from './GraphCanvas.icons'

type Props = {
  pinnedPaths: string[]
  graph: GraphData | null
  selectedPath: string | null
  compactMode: boolean
  hoverRevealBlock: string
  label: (icon: React.ReactNode, hotkey?: string) => React.ReactNode
  onGoTo: (path: string) => void | Promise<void>
  onUnpin: (path: string) => void | Promise<void>
  onClearPins: () => void | Promise<void>
}

export function GraphPinsPanel({
  pinnedPaths,
  graph,
  selectedPath,
  compactMode,
  hoverRevealBlock,
  label,
  onGoTo,
  onUnpin,
  onClearPins,
}: Props) {
  if (pinnedPaths.length === 0) return null
  return (
    <div className="group absolute bottom-3 left-3 z-10 w-[360px] max-w-[calc(100vw-24px)] rounded-md bg-neutral-950/80 border border-neutral-800 px-3 py-2 shadow-lg">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-semibold text-neutral-200">
          Pinned ({pinnedPaths.length}/3)
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-[11px] font-semibold"
            onClick={() => onClearPins()}
            title="Clear all pins"
            aria-label="Clear all pins"
          >
            {label(<ClearIcon />)}
          </button>
        </div>
      </div>
      <div className="mt-2 flex flex-col gap-2">
        {pinnedPaths.map((p) => {
          const n = graph?.nodes?.find((x) => x.path === p || x.id === p)
          const active = selectedPath === p
          const risk = n ? Number(n.risk ?? 0) : null
          const loc = n ? Number(n.loc ?? 0) : null
          const fi = n ? Number(n.fan_in ?? 0) : null
          const fo = n ? Number(n.fan_out ?? 0) : null
          return (
            <div
              key={p}
              className={[
                'rounded-md border px-2 py-2',
                active ? 'bg-neutral-900 border-neutral-700' : 'bg-neutral-950 border-neutral-900',
              ].join(' ')}
              title={p}
            >
              <div className="flex items-start justify-between gap-2">
                <button
                  type="button"
                  className="min-w-0 flex-1 text-left"
                  onClick={() => void onGoTo(p)}
                  title="Go to node"
                >
                  <div className="text-xs font-semibold text-neutral-100 truncate">
                    {baseName(p)}
                    {compactMode && (
                      <span className="ml-2 text-[11px] text-neutral-400">
                        R:{risk != null ? risk.toFixed(2) : '—'}
                      </span>
                    )}
                  </div>
                  {!compactMode && <div className="text-[11px] text-neutral-500 truncate">{p}</div>}
                </button>
                <button
                  type="button"
                  className="shrink-0 text-neutral-400 hover:text-neutral-100"
                  onClick={() => onUnpin(p)}
                  aria-label="Unpin"
                  title="Unpin"
                >
                  ×
                </button>
              </div>
              {!compactMode && (
                <div className="mt-1 text-[11px] text-neutral-300">
                  Risk: <span className="text-neutral-100">{risk != null ? risk.toFixed(2) : '—'}</span>
                  {' · '}
                  LOC: <span className="text-neutral-100">{loc != null ? String(loc) : '—'}</span>
                  {' · '}
                  In: <span className="text-neutral-100">{fi != null ? String(fi) : '—'}</span>
                  {' · '}
                  Out: <span className="text-neutral-100">{fo != null ? String(fo) : '—'}</span>
                  {!n && <span className="text-neutral-500"> · not in current graph</span>}
                </div>
              )}
            </div>
          )
        })}
      </div>
      {pinnedPaths.length >= 2 && (
        <div className={['mt-3 border-t border-neutral-800 pt-2', hoverRevealBlock].join(' ')}>
          <div className="text-[11px] text-neutral-400 font-semibold">Compare (Δ vs first pinned)</div>
          {(() => {
            const basePath = pinnedPaths[0]
            const base = graph?.nodes?.find((x) => x.path === basePath || x.id === basePath)
            const br = base ? Number(base.risk ?? 0) : null
            const bl = base ? Number(base.loc ?? 0) : null
            const bi = base ? Number(base.fan_in ?? 0) : null
            const bo = base ? Number(base.fan_out ?? 0) : null
            return (
              <div className="mt-1 space-y-1">
                {pinnedPaths.slice(1).map((pp) => {
                  const n = graph?.nodes?.find((x) => x.path === pp || x.id === pp)
                  const r = n ? Number(n.risk ?? 0) : null
                  const l = n ? Number(n.loc ?? 0) : null
                  const fi = n ? Number(n.fan_in ?? 0) : null
                  const fo = n ? Number(n.fan_out ?? 0) : null
                  const d = (a: number | null, b: number | null) => (a != null && b != null ? (a - b) : null)
                  return (
                    <div key={pp} className="text-[11px] text-neutral-300">
                      <span className="text-neutral-100">{baseName(pp)}</span>
                      {' · '}
                      ΔRisk: <span className="text-neutral-100">{d(r, br)?.toFixed?.(2) ?? '—'}</span>
                      {' · '}
                      ΔLOC: <span className="text-neutral-100">{d(l, bl) != null ? String(d(l, bl)) : '—'}</span>
                      {' · '}
                      ΔIn/Out: <span className="text-neutral-100">{d(fi, bi) != null && d(fo, bo) != null ? `${d(fi, bi)}/${d(fo, bo)}` : '—'}</span>
                    </div>
                  )
                })}
              </div>
            )
          })()}
        </div>
      )}
    </div>
  )
}
