// frontend/src/ui/hooks/useCytoscapeGraph.ts
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Core, ElementDefinition } from 'cytoscape'
import type { GraphData } from '@/api'
import { riskColor } from '@/shared/lib/riskColor'
import { useCytoscapeActions } from './useCytoscapeActions'
import { buildGraphElements } from '../lib/graphElements'
import { runStarburst } from '../lib/starburst'
import { runApplyFilters } from '../lib/applyGraphFilters'
import { buildStylesheet } from '../lib/graphStylesheet'
import { safeStorageGet, safeStorageRemove, safeStorageSet } from '@/shared/lib/storage'
import {
  DEFAULT_LAYOUT,
  BATCH_SIZE,
  DIM_NODE_OPACITY,
  DIM_EDGE_OPACITY,
  STRONG_EDGE_OPACITY,
  PINNED_BORDER,
  LABEL_ZOOM_THRESHOLD,
  MAX_NEIGHBOR_LABELS,
  EDGE_BATCH_SIZE,
  DOUBLE_TAP_MS,
  CENTER_MIN_ZOOM,
  CENTER_MAX_ZOOM,
  CENTER_RETRY_ATTEMPTS,
  CENTER_RETRY_DELAY_MS,
  GRID_SPACING,
  LOCK_BORDER,
  NODE_SIZE_MIN,
  NODE_SIZE_MAX,
  STAR_ARC_PAD,
  STAR_BASE_RADIUS_IN,
  STAR_BASE_RADIUS_OUT,
  STAR_RING_SPACING,
  STAR_MAX_NEIGHBORS,
  STAR_ANIMATE_MAX,
  clamp,
  safeStr,
  toFiniteNumber,
  nodeSizeFromRisk,
  makeUniqueId,
} from '../lib/useCytoscapeGraph.constants'
import type {
  GraphFilters,
  GraphStats,
  LabelMode,
  EdgeDirectionHighlight,
  NodeContextMenuPayload,
  GraphEditSnapshot,
  GraphEditEvent,
} from '../lib/useCytoscapeGraph.constants'

export type {
  GraphFilters,
  GraphStats,
  LabelMode,
  EdgeDirectionHighlight,
  NodeContextMenuPayload,
  GraphEditSnapshot,
  GraphEditEvent,
} from '../lib/useCytoscapeGraph.constants'

export function useCytoscapeGraph({
  graph,
  filters,
  selectedPath,
  onBackgroundTap,
  onNodeTap,
  onNodeDoubleTap,
  onNodeContextMenu,
  enableStarburst = true,
  onEditEvent,
  spotlight = true,
  labelMode = 'auto',
  pinnedPaths = [],
  edgeDirectionHighlight,
}: {
  graph: GraphData | null
  filters: GraphFilters
  selectedPath: string | null
  onBackgroundTap: () => void
  onNodeTap: (path: string) => void | Promise<void>
  onNodeDoubleTap?: (path: string) => void | Promise<void>
  onNodeContextMenu?: (p: NodeContextMenuPayload) => void
  enableStarburst?: boolean
  onEditEvent?: (e: GraphEditEvent) => void
  spotlight?: boolean
  labelMode?: LabelMode
  pinnedPaths?: string[]
  edgeDirectionHighlight?: Partial<EdgeDirectionHighlight>
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const cyRef = useRef<Core | null>(null)
  const chunkTimerRef = useRef<number | null>(null)
  const applyFiltersRef = useRef<() => void>(() => {})
  const zoomTimerRef = useRef<number | null>(null)
  const lastTapRef = useRef<{ path: string; time: number } | null>(null)

  const enableStarburstRef = useRef<boolean>(Boolean(enableStarburst))
  useEffect(() => {
    enableStarburstRef.current = Boolean(enableStarburst)
  }, [enableStarburst])

  const [instanceId, setInstanceId] = useState(0)
  const hiddenKeysRef = useRef<Set<string>>(new Set())
  const lockedKeysRef = useRef<Set<string>>(new Set())

  const onBackgroundTapRef = useRef(onBackgroundTap)
  const onNodeTapRef = useRef(onNodeTap)
  const onNodeDoubleTapRef = useRef(onNodeDoubleTap)
  const onNodeContextMenuRef = useRef(onNodeContextMenu)
  const onEditEventRef = useRef(onEditEvent)
  useEffect(() => { onBackgroundTapRef.current = onBackgroundTap }, [onBackgroundTap])
  useEffect(() => { onNodeTapRef.current = onNodeTap }, [onNodeTap])
  useEffect(() => { onNodeDoubleTapRef.current = onNodeDoubleTap }, [onNodeDoubleTap])
  useEffect(() => { onNodeContextMenuRef.current = onNodeContextMenu }, [onNodeContextMenu])
  useEffect(() => { onEditEventRef.current = onEditEvent }, [onEditEvent])

  const [stats, setStats] = useState<GraphStats>({ totalNodes: 0, visibleNodes: 0, hydrating: false })

  const edgeDirEnabled = Boolean(edgeDirectionHighlight?.enabled ?? true)
  const normalizeColor = (v: unknown, fallback: string) => {
    const s = safeStr(v)
    if (!s) return fallback
    const m = s.match(/^rgb\(\s*(\d+)\s+(\d+)\s+(\d+)\s*\)$/i)
    if (m) return `rgb(${m[1]},${m[2]},${m[3]})`
    return s
  }
  const edgeDirInColor = normalizeColor(edgeDirectionHighlight?.inColor, '#22c55e')
  const edgeDirOutColor = normalizeColor(edgeDirectionHighlight?.outColor, '#3b82f6')

  const pinnedSet = useMemo(() => {
    return new Set((pinnedPaths || []).filter((x) => typeof x === 'string' && x.trim()))
  }, [pinnedPaths])

  const isHiddenNode = useCallback((n: any) => {
    try {
      const id = safeStr(n.id?.())
      const path = safeStr(n.data?.('path'))
      const key = safeStr(path || id)
      return (id && hiddenKeysRef.current.has(id)) || (path && hiddenKeysRef.current.has(path)) || (key && hiddenKeysRef.current.has(key))
    } catch {
      return false
    }
  }, [])

  const { nodes, edges } = useMemo(() => buildGraphElements(graph), [graph])

  const clearChunkTimer = useCallback(() => {
    if (chunkTimerRef.current != null) {
      window.clearTimeout(chunkTimerRef.current)
      chunkTimerRef.current = null
    }
  }, [])

  const clearZoomTimer = useCallback(() => {
    if (zoomTimerRef.current != null) {
      window.clearTimeout(zoomTimerRef.current)
      zoomTimerRef.current = null
    }
  }, [])

  const animateCenterTo = useCallback((eles: any) => {
    try {
      const cy = cyRef.current
      if (!cy) return
      const z0 = cy.zoom()
      const z = Number.isFinite(z0) ? Number(z0) : 1
      const nextZoom = clamp(z, CENTER_MIN_ZOOM, CENTER_MAX_ZOOM)
      try {
        cy.stop()
      } catch {}
      cy.animate({ center: { eles }, zoom: nextZoom }, { duration: 220 })
    } catch {
      // ignore
    }
  }, [])

  // --- Star-map: раскладка inbound/outbound вокруг выбранного узла ---
  const starburstNeighborhood = useCallback(
    (selectedNode: any) => {
      const cy = cyRef.current
      if (!cy) return
      runStarburst(cy, pinnedSet, selectedNode)
    },
    [pinnedSet],
  )

  const starburstRef = useRef<((n: any) => void) | null>(null)
  useEffect(() => {
    starburstRef.current = starburstNeighborhood
  }, [starburstNeighborhood])

  const applyFilters = useCallback(() => {
    const cy = cyRef.current
    if (!cy) return
    runApplyFilters(cy, {
      filters, selectedPath, spotlight, edgeDirEnabled, labelMode,
      pinnedSet, isHiddenNode, lockedKeysRef, setStats,
    })
  }, [
    filters.minRisk,
    filters.onlySelectionNeighborhood,
    filters.text,
    labelMode,
    pinnedSet,
    selectedPath,
    spotlight,
    edgeDirEnabled,
  ])

  // даём доступ к актуальной версии applyFilters из обработчиков, не пересоздавая cy
  useEffect(() => {
    applyFiltersRef.current = applyFilters
  }, [applyFilters])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    if (!graph) {
      cyRef.current?.destroy()
      cyRef.current = null
      hiddenKeysRef.current = new Set()
      lockedKeysRef.current = new Set()
      setStats({ totalNodes: 0, visibleNodes: 0, hydrating: false })
      return
    }

    setInstanceId((x) => x + 1)
    
    hiddenKeysRef.current = new Set()
    lockedKeysRef.current = new Set()

    clearChunkTimer()
    clearZoomTimer()

    if (cyRef.current) {
      cyRef.current.destroy()
      cyRef.current = null
    }

    let cancelled = false
    let ro: ResizeObserver | null = null

    ;(async () => {
      const cytoscape = (await import('cytoscape')).default
      if (cancelled) return

      const cy = cytoscape({
        container,
        elements: [],
        style: buildStylesheet(edgeDirInColor, edgeDirOutColor) as any,
        layout: DEFAULT_LAYOUT,
        wheelSensitivity: 0.14,
        minZoom: 0.18,
        maxZoom: 3.0,
      })

      cy.on('tap', (evt) => {
        if (evt.target !== cy) return
        lastTapRef.current = null
        onBackgroundTapRef.current?.()
      })

      cy.on('grab', 'node', () => {
        onEditEventRef.current?.({ kind: 'dragstart' })
      })
      cy.on('dragfree', 'node', () => {
        onEditEventRef.current?.({ kind: 'dragend' })
      })

      cy.on('zoom', () => {
        if (zoomTimerRef.current != null) window.clearTimeout(zoomTimerRef.current)
        zoomTimerRef.current = window.setTimeout(() => {
          zoomTimerRef.current = null
          applyFiltersRef.current()
        }, 60)
      })

      cy.on('mouseover', 'node', (evt) => {
        try {
          evt.target.addClass('cs-hover')
        } catch {}
      })
      cy.on('mouseout', 'node', (evt) => {
        try {
          evt.target.removeClass('cs-hover')
        } catch {}
      })

      cy.on('tap', 'node', (evt) => {
        const node = evt.target
        const path = (node.data('path') as string) || node.id()
        const now = Date.now()
        const prev = lastTapRef.current
        if (prev && prev.path === path && now - prev.time <= DOUBLE_TAP_MS) {
          lastTapRef.current = null
          void onNodeDoubleTapRef.current?.(path)
        } else {
          lastTapRef.current = { path, time: now }
        }
        void onNodeTapRef.current?.(path)
      })

      cy.on('cxttap', 'node', (evt: any) => {
        try {
          evt?.originalEvent?.preventDefault?.()
        } catch {}
        lastTapRef.current = null
        const node = evt.target
        const path = (node.data('path') as string) || node.id()
        const rp = evt?.renderedPosition
        const x = Number.isFinite(Number(rp?.x)) ? Number(rp.x) : 0
        const y = Number.isFinite(Number(rp?.y)) ? Number(rp.y) : 0
        onNodeContextMenuRef.current?.({ path, x, y })
      })

      cyRef.current = cy

      try {
        ro = new ResizeObserver(() => {
          try {
            cy.resize()
          } catch {}
        })
        ro.observe(container)
      } catch {}

      const returnedNodes = Number.isFinite(Number(graph?.meta?.returned_nodes)) ? Number(graph?.meta?.returned_nodes) : nodes.length
      const hydrating0 = nodes.length > BATCH_SIZE || edges.length > EDGE_BATCH_SIZE
      setStats({ totalNodes: returnedNodes, visibleNodes: nodes.length, hydrating: hydrating0 })

      const addChunk = (offset: number) => {
        if (cancelled || !cyRef.current) return
        const next = offset + BATCH_SIZE
        const chunk = nodes.slice(offset, next)

        if (chunk.length) {
          try {
            cyRef.current.add(chunk)
          } catch {
            // если что-то всё же невалидно — не валим весь граф
          }
        }

        if (next < nodes.length) {
          chunkTimerRef.current = window.setTimeout(() => addChunk(next), 20)
          return
        }

        const addEdgesChunk = (edgeOffset: number) => {
          if (cancelled || !cyRef.current) return
          const nextEdge = edgeOffset + EDGE_BATCH_SIZE
          const chunkEdges = edges.slice(edgeOffset, nextEdge)

          if (chunkEdges.length) {
            try {
              cyRef.current.add(chunkEdges)
            } catch {
              // ignore (but chunking makes failures far less likely)
            }
          }

          if (nextEdge < edges.length) {
            chunkTimerRef.current = window.setTimeout(() => addEdgesChunk(nextEdge), 20)
            return
          }

          const cyNow = cyRef.current
          if (cyNow) {
            const layout: any = cyNow.layout(DEFAULT_LAYOUT)
            layout.on('layoutstop', () => {
              try {
                cyNow.fit(cyNow.elements(':visible'), 60)
              } catch {}
            })
            layout.run()
          }
          setStats((prev) => ({ ...prev, hydrating: false }))
          applyFiltersRef.current()
        }

        if (!edges.length) {
          const cyNow = cyRef.current
          if (cyNow) {
            const layout: any = cyNow.layout(DEFAULT_LAYOUT)
            layout.on('layoutstop', () => {
              try { cyNow.fit(cyNow.elements(':visible'), 60) } catch {}
            })
            layout.run()
          }
          setStats((prev) => ({ ...prev, hydrating: false }))
          applyFiltersRef.current()
          return
        }

        addEdgesChunk(0)
      }

      addChunk(0)
    })()

    return () => {
      cancelled = true
      clearChunkTimer()
      clearZoomTimer()
      try {
        cyRef.current?.destroy()
      } catch {}
      try {
        ro?.disconnect()
      } catch {}
      cyRef.current = null
    }
  }, [clearChunkTimer, clearZoomTimer, edges, graph, nodes, edgeDirInColor, edgeDirOutColor])

  useEffect(() => {
    applyFilters()
  }, [applyFilters])

  // Выделение + star-map (с ретраями, если граф ещё гидратится)
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return

    try { cy.nodes().unselect() } catch {}
    const wanted = safeStr(selectedPath)
    if (!wanted) return

    let cancelled = false
    let attempt = 0

    const trySelect = () => {
      if (cancelled) return
      const cyNow = cyRef.current
      if (!cyNow) return

      const match = cyNow.nodes().filter((n) => n.data('path') === wanted || n.id() === wanted)
      if (match && match.length) {
        match.select()
        applyFiltersRef.current()

        if (enableStarburstRef.current) {
          starburstRef.current?.(match[0])
        }

        const centerTarget = match.closedNeighborhood()
        const visibleTarget = centerTarget.filter(':visible')
        animateCenterTo(visibleTarget.empty() ? match : visibleTarget)
        
        return
      }

      attempt += 1
      if (attempt < CENTER_RETRY_ATTEMPTS) {
        window.setTimeout(trySelect, CENTER_RETRY_DELAY_MS)
      }
    }

    trySelect()
    return () => {
      cancelled = true
    }
  }, [selectedPath, instanceId, animateCenterTo])

  useEffect(() => clearChunkTimer, [clearChunkTimer])

  const actions = useCytoscapeActions({
    cyRef,
    hiddenKeysRef,
    lockedKeysRef,
    applyFiltersRef,
    animateCenterTo,
    isHiddenNode,
  })

  return {
    containerRef,
    stats,
    instanceId,
    actions,
  }
}

export type CytoscapeGraphActions = ReturnType<typeof useCytoscapeGraph>['actions']
