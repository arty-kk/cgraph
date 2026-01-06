// frontend/src/ui/components/GraphCanvas.tsx
import React, { useEffect, useMemo, useRef } from 'react'
import Cytoscape from 'cytoscape'
import type { GraphData, Project } from '../../api'
import { riskColor } from '../../lib/riskColor'

type Props = {
  graph: GraphData | null
  activeProject: Project | null
  busy: boolean
  selectedPath: string | null
  onBackgroundTap: () => void
  onNodeTap: (path: string) => void | Promise<void>
}

export function GraphCanvas({ graph, activeProject, busy, selectedPath, onBackgroundTap, onNodeTap }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const cyRef = useRef<Cytoscape.Core | null>(null)

  const elements = useMemo<Cytoscape.ElementDefinition[]>(() => {
    if (!graph) return []
    return [
      ...graph.nodes.map((n) => ({
        data: {
          id: n.id,
          label: n.label,
          path: n.path,
          risk: Number(n.risk ?? 0),
          status: n.status,
          scc: n.scc_id,
        },
      })),
      ...graph.edges.map((e, i) => ({
        data: { id: `e${i}`, source: e.source, target: e.target, kind: e.kind },
      })),
    ]
  }, [graph])

  // init / re-init on graph changes
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    if (!graph) {
      if (cyRef.current) {
        cyRef.current.destroy()
        cyRef.current = null
      }
      return
    }

    if (cyRef.current) {
      cyRef.current.destroy()
      cyRef.current = null
    }

    const c = Cytoscape({
      container,
      elements,
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            'font-size': 10,
            'text-valign': 'center',
            'text-halign': 'center',
            width: 18,
            height: 18,
            'background-color': (ele) => riskColor(Number(ele.data('risk') ?? 0)),
            'border-width': 1,
            'border-color': '#111827',
            color: '#e5e7eb',
          },
        },
        {
          selector: 'edge',
          style: {
            width: 1,
            'line-color': '#334155',
            'target-arrow-color': '#334155',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
          },
        },
        {
          selector: 'node:selected',
          style: {
            'border-width': 3,
            'border-color': '#e5e7eb',
          },
        },
      ],
      layout: { name: 'cose', animate: false, fit: true },
    })
    // Ensure correct initial sizing (especially after mount / StrictMode dev behavior).
    c.on('tap', (evt) => {
      if (evt.target !== c) return
      onBackgroundTap()
    })

    c.on('tap', 'node', (evt) => {
      const node = evt.target
      const path = (node.data('path') as string) || node.id()
      void onNodeTap(path)
    })

    cyRef.current = c

    // Keep Cytoscape in sync with container resizes (window resize, layout changes, etc.)
    let ro: ResizeObserver | null = null
    try {
      ro = new ResizeObserver(() => {
        try {
          c.resize()
        } catch {
          // ignore
        }
      })
      ro.observe(container)
    } catch {
      // ResizeObserver may be unavailable in some environments; ignore.
    }

    // Next frame: resize to avoid measuring 0x0 before layout settles.
    try {
      requestAnimationFrame(() => c.resize())
    } catch {
      // ignore
    }
    return () => {
      try { ro?.disconnect() } catch { /* ignore */ }
      c.destroy()
      if (cyRef.current === c) cyRef.current = null
    }
  }, [graph, elements, onBackgroundTap, onNodeTap])

  // sync selection without re-init
  useEffect(() => {
    const c = cyRef.current
    if (!c) return
    c.nodes().unselect()
    if (!selectedPath) return
    const match = c.nodes().filter((n) => n.data('path') === selectedPath || n.id() === selectedPath)
    if (match.length) match.select()
  }, [selectedPath])

  return (
    <div className="relative w-full h-full">
      <div className="absolute top-3 left-3 z-10 flex items-center gap-2 bg-neutral-950/70 border border-neutral-800 rounded-md px-3 py-2">
        <div className="text-xs text-neutral-300">
          {activeProject ? (
            <>
              <span className="font-semibold">{activeProject.name}</span>
              <span className="ml-2 text-neutral-400">
                {graph ? (() => {
                  const meta: any = (graph as any).meta
                  const tn = Number.isFinite(Number(meta?.total_nodes)) ? Number(meta.total_nodes) : null
                  const te = Number.isFinite(Number(meta?.total_edges)) ? Number(meta.total_edges) : null
                  const truncated = !!meta?.truncated
                  if (tn != null && te != null) {
                    const shown = `${graph.nodes.length} nodes / ${graph.edges.length} edges`
                    const total = `${tn} total / ${te} total`
                    const base = truncated ? `${shown} (shown of ${total}, truncated)` : `${shown} (of ${total})`
                    return busy ? `${base} · refreshing…` : base
                  }
                  const base = `${graph.nodes.length} nodes / ${graph.edges.length} edges`
                  return busy ? `${base} · refreshing…` : base
                })() : busy ? 'loading…' : '—'}
              </span>
            </>
          ) : (
            'Выбери проект'
          )}
        </div>
      </div>
      <div ref={containerRef} className="w-full h-full" />
    </div>
  )
}
