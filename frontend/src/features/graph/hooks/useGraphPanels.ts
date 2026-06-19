import { useEffect, useMemo, useRef, useState } from 'react'
import type { GraphData } from '@/api'

type Params = {
  graph: GraphData | null
  selectedPath: string | null
}

/**
 * Owns the control-panel/neighbors/help open state, the click-outside dismiss
 * for the control panel, and the derived inbound/outbound neighbor lists for
 * the currently selected node. Extracted verbatim from GraphCanvas.
 */
export function useGraphPanels({ graph, selectedPath }: Params) {
  const [panelOpen, setPanelOpen] = useState(false)
  const [neighborsOpen, setNeighborsOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)

  const panelRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!panelOpen) return
    const onDown = (e: MouseEvent) => {
      const el = e.target as Node | null
      if (!el) return
      if (panelRef.current && panelRef.current.contains(el)) return
      setPanelOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [panelOpen])

  const neighbors = useMemo(() => {
    const inSet = new Set<string>()
    const outSet = new Set<string>()
    if (!graph || !selectedPath) return { inbound: [] as string[], outbound: [] as string[] }

    const keyToPath = new Map<string, string>()
    for (const n of graph.nodes || []) {
      const id = typeof (n as any)?.id === 'string' ? String((n as any).id) : ''
      const path = typeof (n as any)?.path === 'string' ? String((n as any).path) : ''
      if (path) keyToPath.set(path, path)
      if (id && path) keyToPath.set(id, path)
      if (id && !keyToPath.has(id)) keyToPath.set(id, id)
    }

    const selNode =
      (graph.nodes || []).find((n: any) => n?.path === selectedPath || n?.id === selectedPath) ?? null
    const selId = selNode && typeof (selNode as any).id === 'string' ? String((selNode as any).id) : null

    const isSel = (k: string) => k === selectedPath || (selId != null && k === selId)
    const toPath = (k: string) => keyToPath.get(k) || k

    for (const e of graph.edges || []) {
      const s = typeof (e as any)?.source === 'string' ? String((e as any).source) : ''
      const t = typeof (e as any)?.target === 'string' ? String((e as any).target) : ''
      if (!s || !t) continue
      if (isSel(t)) inSet.add(toPath(s))
      if (isSel(s)) outSet.add(toPath(t))
    }

    const inbound = Array.from(inSet).filter(Boolean).sort()
    const outbound = Array.from(outSet).filter(Boolean).sort()
    return { inbound, outbound }
  }, [graph, selectedPath])

  useEffect(() => {
    setNeighborsOpen(false)
  }, [selectedPath])

  return {
    panelOpen,
    setPanelOpen,
    neighborsOpen,
    setNeighborsOpen,
    helpOpen,
    setHelpOpen,
    panelRef,
    neighbors,
  }
}
