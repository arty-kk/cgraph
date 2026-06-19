import type { ElementDefinition } from 'cytoscape'
import type { GraphData } from '@/api'
import { safeStr, toFiniteNumber, makeUniqueId, GRID_SPACING } from './useCytoscapeGraph.constants'

/**
 * Pure transform of API graph data into cytoscape element definitions.
 * Assigns unique canonical ids, lays nodes out on a grid, tags the
 * highest-risk nodes with cs-important / cs-glow classes, and drops edges
 * whose endpoints are missing. Extracted verbatim from useCytoscapeGraph.
 */
export function buildGraphElements(
  graph: GraphData | null,
): { nodes: ElementDefinition[]; edges: ElementDefinition[] } {
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
}
