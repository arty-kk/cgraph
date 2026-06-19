import type { Core } from 'cytoscape'
import {
  safeStr,
  toFiniteNumber,
  STAR_MAX_NEIGHBORS,
  STAR_RING_SPACING,
  STAR_ARC_PAD,
  STAR_BASE_RADIUS_IN,
  STAR_BASE_RADIUS_OUT,
  STAR_ANIMATE_MAX,
} from './useCytoscapeGraph.constants'

/**
 * Fan the inbound/outbound neighbors of a selected node out into upper/lower
 * arcs around it (skipping hidden and pinned nodes, capped per side and sorted
 * by risk). Animates when the count is small. Extracted verbatim from
 * useCytoscapeGraph; the caller supplies the live cy instance.
 */
export function runStarburst(cy: Core, pinnedSet: Set<string>, selectedNode: any): void {
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
}
