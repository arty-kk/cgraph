// frontend/src/ui/hooks/useCytoscapeGraph.ts
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { Core, ElementDefinition } from 'cytoscape'
import type { GraphData } from '@/api'
import { riskColor } from '@/shared/lib/riskColor'
import { useCytoscapeActions } from './useCytoscapeActions'
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
} from './useCytoscapeGraph.constants'
import type {
  GraphFilters,
  GraphStats,
  LabelMode,
  EdgeDirectionHighlight,
  NodeContextMenuPayload,
  GraphEditSnapshot,
  GraphEditEvent,
} from './useCytoscapeGraph.constants'

export type {
  GraphFilters,
  GraphStats,
  LabelMode,
  EdgeDirectionHighlight,
  NodeContextMenuPayload,
  GraphEditSnapshot,
  GraphEditEvent,
} from './useCytoscapeGraph.constants'

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

  const { nodes, edges } = useMemo(() => {
    if (!graph) return { nodes: [] as ElementDefinition[], edges: [] as ElementDefinition[] }

    const usedIds = new Set<string>()
    const idByKey = new Map<string, string>()

    const normalized = (graph.nodes || []).map((n: any, idx: number) => {
      const pathKey = safeStr(n?.path)
      const idKey = safeStr(n?.id)
      const base = pathKey || idKey || `n${idx}`
      const canonical = makeUniqueId(base, usedIds)

      if (idKey) idByKey.set(idKey, canonical)
      if (pathKey) idByKey.set(pathKey, canonical)
      idByKey.set(canonical, canonical)

      return { n, canonical, pathKey }
    })

    const sortedByRisk = [...normalized].sort(
      (a, b) => toFiniteNumber(b.n?.risk, 0) - toFiniteNumber(a.n?.risk, 0),
    )

    const importantIds = new Set<string>()
    sortedByRisk
      .slice(0, Math.min(18, normalized.length))
      .forEach((x) => importantIds.add(x.canonical))

    const glowIds = new Set<string>()
    sortedByRisk
      .slice(0, Math.min(6, normalized.length))
      .forEach((x) => glowIds.add(x.canonical))

    const total = normalized.length
    const cols = Math.max(1, Math.ceil(Math.sqrt(total)))
    const rows = Math.max(1, Math.ceil(total / cols))
    const width = (cols - 1) * GRID_SPACING
    const height = (rows - 1) * GRID_SPACING
    const ox = -width / 2
    const oy = -height / 2

    const nodeElements: ElementDefinition[] = normalized.map(({ n, canonical, pathKey }, i) => {
      const label = safeStr(n?.label) || pathKey || canonical
      const path = pathKey || canonical
      const col = i % cols
      const row = Math.floor(i / cols)
      const x = ox + col * GRID_SPACING
      const y = oy + row * GRID_SPACING

      const classes = [
        importantIds.has(canonical) ? 'cs-important' : '',
        glowIds.has(canonical) ? 'cs-glow' : '',
      ]
        .filter(Boolean)
        .join(' ')

      return {
        data: {
          id: canonical,
          label,
          path,
          risk: toFiniteNumber(n?.risk, 0),
          status: n?.status,
          scc: n?.scc_id,
        },
        position: { x, y },
        classes,
      }
    })

    const edgeElements: ElementDefinition[] = (graph.edges || [])
      .map((e: any, i: number) => {
        const sourceKey = safeStr(e?.source)
        const targetKey = safeStr(e?.target)
        const source = idByKey.get(sourceKey) || sourceKey
        const target = idByKey.get(targetKey) || targetKey
        return { data: { id: `e${i}`, source, target, kind: e?.kind } }
      })
      .filter((ed) => {
        const s = safeStr((ed as any).data?.source)
        const t = safeStr((ed as any).data?.target)
        // edge требует валидные source/target (иначе Cytoscape может ругаться/ломать добавление)
        return !!s && !!t && usedIds.has(s) && usedIds.has(t)
      })

    return { nodes: nodeElements, edges: edgeElements }
  }, [graph])

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
      if (!cy || !selectedNode) return

      // если скрыт фильтрами — не трогаем
      try {
        if (selectedNode.style('display') === 'none') return
      } catch {
        // ignore
      }

      const center = selectedNode.position()
      if (!center || !Number.isFinite(center.x) || !Number.isFinite(center.y)) return

      const isMovableNeighbor = (n: any) => {
        if (!n) return false
        if (n.id() === selectedNode.id()) return false
        try {
          if (n.style('display') === 'none') return false
        } catch {
          // ignore
        }
        const key = safeStr(n.data('path')) || safeStr(n.id())
        if (key && pinnedSet.has(key)) return false
        return true
      }

      // inbound / outbound
      let inArr: any[] = []
      let outArr: any[] = []

      try {
        inArr = selectedNode.incomers('node').filter((n: any) => isMovableNeighbor(n)).toArray()
      } catch {
        inArr = []
      }

      try {
        outArr = selectedNode.outgoers('node').filter((n: any) => isMovableNeighbor(n)).toArray()
      } catch {
        outArr = []
      }

      if (!inArr.length && !outArr.length) return

      // ограничим, чтобы не превращать в лаг-генератор на узлах с огромной степенью
      const cap = STAR_MAX_NEIGHBORS
      const capList = (arr: any[]) => {
        if (arr.length <= cap) return arr
        return arr
          .slice()
          .sort((a, b) => toFiniteNumber(b.data('risk'), 0) - toFiniteNumber(a.data('risk'), 0))
          .slice(0, cap)
      }
      inArr = capList(inArr)
      outArr = capList(outArr)

      // сортируем, чтобы более “важные” попадали ближе
      const byRiskDesc = (a: any, b: any) => toFiniteNumber(b.data('risk'), 0) - toFiniteNumber(a.data('risk'), 0)
      inArr.sort(byRiskDesc)
      outArr.sort(byRiskDesc)

      const positions: Array<{ node: any; pos: { x: number; y: number } }> = []

      const placeArc = (arr: any[], start: number, end: number, baseRadius: number) => {
        const n = arr.length
        if (!n) return

        const span = end - start
        const step = n === 1 ? 0 : span / (n - 1)

        const rings = Math.min(6, Math.max(1, Math.ceil(n / 10)))
        const dynamicBase = baseRadius + Math.min(220, Math.sqrt(n) * 55)

        for (let i = 0; i < n; i++) {
          const ring = i % rings
          const angle = start + step * i + (rings > 1 ? (ring - (rings - 1) / 2) * step * 0.22 : 0)
          const radius = dynamicBase + ring * STAR_RING_SPACING

          const x = center.x + Math.cos(angle) * radius
          const y = center.y + Math.sin(angle) * radius
          positions.push({ node: arr[i], pos: { x, y } })
        }
      }

      // inbound — верхняя полуокружность, outbound — нижняя
      placeArc(inArr, -Math.PI + STAR_ARC_PAD, -STAR_ARC_PAD, STAR_BASE_RADIUS_IN)
      placeArc(outArr, STAR_ARC_PAD, Math.PI - STAR_ARC_PAD, STAR_BASE_RADIUS_OUT)

      try {
        cy.stop()
      } catch {}

      const doAnimate = positions.length > 0 && positions.length <= STAR_ANIMATE_MAX
      if (doAnimate) {
        for (const { node, pos } of positions) {
          try {
            node.animate({ position: pos }, { duration: 260 })
          } catch {
            try {
              node.position(pos)
            } catch {}
          }
        }
      } else {
        cy.batch(() => {
          for (const { node, pos } of positions) {
            try {
              node.position(pos)
            } catch {
              // ignore
            }
          }
        })
      }
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

    const zoomRaw = cy.zoom()
    const zoom = Number.isFinite(zoomRaw) ? Number(zoomRaw) : 1
    const zoomOk = zoom >= LABEL_ZOOM_THRESHOLD

    const query = filters.text.trim().toLowerCase()
    const minRisk = filters.minRisk

    const selected = selectedPath
      ? cy.nodes().filter((n) => n.data('path') === selectedPath || n.id() === selectedPath)
      : cy.collection()

    const hasSelection = !selected.empty()
    const neighborhood = hasSelection ? selected.closedNeighborhood() : cy.collection()
    const neighborhoodNodes = neighborhood.nodes()
    const neighborhoodEdges = neighborhood.edges()

    const allowNeighborhoodLabels = zoomOk && neighborhoodNodes.length <= MAX_NEIGHBOR_LABELS

    const neighborhoodFilterActive = Boolean(filters.onlySelectionNeighborhood && hasSelection)
    const spotlightActive = Boolean(spotlight && hasSelection && !neighborhoodFilterActive)

    const dirActive = Boolean(edgeDirEnabled && hasSelection)
    const inEdgeIds = new Set<string>()
    const outEdgeIds = new Set<string>()
    if (dirActive) {
      try {
        selected.incomers('edge').forEach((e: any) => {
          const id = safeStr(e?.id?.())
          if (id) inEdgeIds.add(id)
        })
      } catch {}
      try {
        selected.outgoers('edge').forEach((e: any) => {
          const id = safeStr(e?.id?.())
          if (id) outEdgeIds.add(id)
        })
      } catch {}
    }

    const visibleNodeIds = new Set<string>()
    let visibleCount = 0

    cy.batch(() => {
      cy.nodes().forEach((n) => {
        const label: string = n.data('label') ?? ''
        const path: string = n.data('path') ?? ''
        const risk = toFiniteNumber(n.data('risk'), 0)

        const isSelectedNode = Boolean(selectedPath) && (path === selectedPath || n.id() === selectedPath)

        if (isHiddenNode(n)) {
          n.style('display', 'none')
          n.removeClass('cs-dim cs-neighbor cs-label cs-pinned cs-locked cs-hover')
          return
        }

        const matchesText = query ? label.toLowerCase().includes(query) || path.toLowerCase().includes(query) : true
        const matchesRisk = Number.isFinite(risk) ? risk >= minRisk : true
        const matchesNeighborhood = neighborhoodFilterActive ? neighborhoodNodes.contains(n) : true

        const visible = (matchesText && matchesRisk && matchesNeighborhood) || isSelectedNode
        n.style('display', visible ? 'element' : 'none')

        n.removeClass('cs-dim cs-neighbor cs-label cs-pinned cs-locked')
        if (!visible) {
          try {
            n.removeClass('cs-hover')
          } catch {}
          return
        }

        visibleNodeIds.add(n.id())
        visibleCount += 1

        const key = safeStr(path || n.id() || '')
        if (key && pinnedSet.has(key)) n.addClass('cs-pinned')

          if ((key && lockedKeysRef.current.has(key)) || lockedKeysRef.current.has(n.id())) {
            try {
              if (!n.locked()) n.lock()
            } catch {}
            n.addClass('cs-locked')
          } else {
            try {
              if (n.locked()) n.unlock()
            } catch {}
          }

        const inSpot = spotlightActive ? neighborhoodNodes.contains(n) : false
        if (spotlightActive && !inSpot) n.addClass('cs-dim')
        if (spotlightActive && inSpot && !n.selected()) n.addClass('cs-neighbor')

        let shouldLabel = false
        if (labelMode === 'on') {
          shouldLabel = true
        } else if (labelMode === 'auto') {
          shouldLabel =
            n.selected() ||
            n.hasClass('cs-hover') ||
            (zoomOk && n.hasClass('cs-important')) ||
            n.hasClass('cs-pinned') ||
            (spotlightActive && inSpot && allowNeighborhoodLabels)
        } else {
          shouldLabel = false
        }

        if (shouldLabel && !n.selected() && !n.hasClass('cs-hover')) {
          n.addClass('cs-label')
        }
      })

      cy.edges().forEach((e) => {
        const src = e.source()
        const tgt = e.target()
        const visible = visibleNodeIds.has(src.id()) && visibleNodeIds.has(tgt.id())

        e.style('display', visible ? 'element' : 'none')
        e.removeClass('cs-dim cs-strong cs-edge-in cs-edge-out')
        if (!visible) return

        if (spotlightActive) {
          const strong = neighborhoodEdges.contains(e)
          if (strong) e.addClass('cs-strong')
          else e.addClass('cs-dim')
        }

        if (dirActive) {
          const eid = safeStr(e.id?.())
          if (eid) {
            if (outEdgeIds.has(eid)) e.addClass('cs-edge-out')
            else if (inEdgeIds.has(eid)) e.addClass('cs-edge-in')
          }
        }
      })
    })

    setStats((prev) => ({ ...prev, visibleNodes: visibleCount }))
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
        style: ([
          {
            selector: 'core',
            style: {
              'active-bg-color': '#e2e8f0',
              'active-bg-opacity': 0.06,
              'active-bg-size': 24,
              'selection-box-color': '#60a5fa',
              'selection-box-border-color': '#93c5fd',
              'selection-box-border-width': 1,
              'selection-box-opacity': 0.12,
            },
          },
          {
            selector: 'node',
            style: {
              label: '',
              shape: 'round-rectangle',
              width: (ele: { data: (k: string) => any }) => nodeSizeFromRisk(ele.data('risk')),
              height: (ele: { data: (k: string) => any }) => nodeSizeFromRisk(ele.data('risk')),
              'background-color': (ele: { data: (k: string) => any }) => riskColor(toFiniteNumber(ele.data('risk'), 0)),
              'background-opacity': 0.98,
              'border-width': 1.5,
              'border-color': '#0b1220',
              'border-opacity': 0.9,
              color: '#e5e7eb',
              'font-size': 10,
              'font-family': 'ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Noto Sans, Helvetica, Arial',
              'text-zooming': 'none',
              'text-valign': 'center',
              'text-halign': 'center',
              'text-outline-color': '#0b1220',
              'text-outline-width': 2,
              'text-outline-opacity': 0.9,
              'transition-property': 'opacity border-color border-width overlay-opacity overlay-padding',
              'transition-duration': '0.12s',
              'transition-timing-function': 'ease-out',
            },
          },
          {
            selector: 'node.cs-important',
            style: {
              'border-width': 2,
              'border-color': '#e2e8f0',
              'overlay-color': '#e2e8f0',
              'overlay-opacity': 0.14,
              'overlay-padding': 10,
            },
          },
          {
            selector: 'node.cs-glow',
            style: {
              'overlay-color': '#e2e8f0',
              'overlay-opacity': 0.2,
              'overlay-padding': 14,
            },
          },
          { selector: 'node.cs-dim', style: { opacity: DIM_NODE_OPACITY } },
          { selector: 'node.cs-neighbor', style: { 'border-width': 2, 'border-color': '#64748b' } },
          {
            selector: 'node.cs-pinned',
            style: {
              'border-width': 3,
              'border-color': PINNED_BORDER,
              'overlay-color': PINNED_BORDER,
              'overlay-opacity': 0.06,
              'overlay-padding': 6,
            },
          },
          {
            selector: 'node.cs-locked',
            style: {
              'border-width': 3,
              'border-color': LOCK_BORDER
            }
          },
          {
            selector: 'node.cs-label',
            style: {
              label: 'data(label)',
              'font-size': 11,
              'text-wrap': 'ellipsis',
              'text-max-width': 240,
              'text-background-color': '#0b1220',
              'text-background-opacity': 0.7,
              'text-background-padding': '3px',
              'text-background-shape': 'roundrectangle',
              'text-border-color': '#334155',
              'text-border-opacity': 0.35,
              'text-border-width': 1,
            },
          },
          {
            selector: 'node.cs-hover',
            style: {
              label: 'data(label)',
              'font-size': 12,
              'text-wrap': 'ellipsis',
              'text-max-width': 280,
              'border-width': 2,
              'border-color': '#e2e8f0',
              'overlay-color': '#e2e8f0',
              'overlay-opacity': 0.08,
              'overlay-padding': 10,
              ghost: 'yes',
              'ghost-offset-x': 0,
              'ghost-offset-y': 2,
              'ghost-opacity': 0.22,
        
              'z-index': 9999,
            },
          },
          {
            selector: 'node:selected',
            style: {
              label: 'data(label)',
              'font-size': 12,
              'text-wrap': 'ellipsis',
              'text-max-width': 320,
              'border-width': 2,
              'border-color': '#f8fafc',
        
              'overlay-color': '#e2e8f0',
              'overlay-opacity': 0.18,
              'overlay-padding': 16,
              ghost: 'yes',
              'ghost-offset-x': 0,
              'ghost-offset-y': 2,
              'ghost-opacity': 0.26,
              'z-index': 9999,
            },
          },
          {
            selector: 'edge',
            style: {
              width: 1.0,
              'curve-style': 'bezier',
              'line-cap': 'round',
              'line-fill': 'solid',
              'line-color': 'rgba(148,163,184,0.30)',
              'mid-target-arrow-shape': 'none',
              'target-arrow-shape': 'none',
              'source-arrow-shape': 'none',
              'arrow-scale': 0.45,
              'source-endpoint': 'outside-to-node-or-label',
              'target-endpoint': 'outside-to-node-or-label',
              opacity: 0.32,
              'transition-property': 'opacity width line-color',
              'transition-duration': '0.12s',
              'transition-timing-function': 'ease-out',
            },
          },
          { 
            selector: 'edge.cs-dim',
            style: { 
              opacity: DIM_EDGE_OPACITY
            }
          },
          {
            selector: 'edge.cs-strong',
            style: {
              opacity: STRONG_EDGE_OPACITY,
              width: 1.7,
              'line-fill': 'solid',
              'line-color': 'rgba(226,232,240,0.90)',
            },
          },
          {
            selector: 'edge.cs-edge-in',
            style: {
              'line-fill': 'solid',
              'line-color': edgeDirInColor,
              opacity: 0.5,
              width: 1,
              'mid-target-arrow-shape': 'none',
              'target-arrow-shape': 'triangle',
              'target-arrow-fill': 'filled',
              'target-arrow-color': edgeDirInColor,
              'arrow-scale': 0.5,
            },
          },
          {
            selector: 'edge.cs-edge-out',
            style: {
              'line-fill': 'solid',
              'line-color': edgeDirOutColor,
              opacity: 0.5,
              width: 1,
              'mid-target-arrow-shape': 'none',
              'target-arrow-shape': 'triangle',
              'source-arrow-fill': 'filled',
              'source-arrow-color': edgeDirOutColor,
              'arrow-scale': 0.5,
            },
          },
        ] as any),        
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
