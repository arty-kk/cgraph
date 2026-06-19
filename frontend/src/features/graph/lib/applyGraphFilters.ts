import type { Dispatch, MutableRefObject, SetStateAction } from 'react'
import type { Core } from 'cytoscape'
import {
  safeStr,
  toFiniteNumber,
  LABEL_ZOOM_THRESHOLD,
  MAX_NEIGHBOR_LABELS,
} from './useCytoscapeGraph.constants'
import type { GraphFilters, GraphStats, LabelMode } from './useCytoscapeGraph.constants'

type Params = {
  filters: GraphFilters
  selectedPath: string | null
  spotlight: boolean
  edgeDirEnabled: boolean
  labelMode: LabelMode
  pinnedSet: Set<string>
  isHiddenNode: (n: any) => boolean | ''
  lockedKeysRef: MutableRefObject<Set<string>>
  setStats: Dispatch<SetStateAction<GraphStats>>
}

/**
 * Recompute node/edge visibility, spotlight dimming, pin/lock classes, edge
 * direction highlighting and which labels show, based on the current filters /
 * selection. Updates stats.visibleNodes. Extracted verbatim from
 * useCytoscapeGraph; the caller supplies the live cy instance.
 */
export function runApplyFilters(cy: Core, params: Params): void {
  const {
    filters, selectedPath, spotlight, edgeDirEnabled, labelMode,
    pinnedSet, isHiddenNode, lockedKeysRef, setStats,
  } = params

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
}
