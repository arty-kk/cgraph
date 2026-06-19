import { describe, expect, it } from 'vitest'
import type { GraphData } from '@/api'
import { buildGraphElements } from './graphElements'

describe('buildGraphElements', () => {
  it('returns empty arrays for a null graph', () => {
    expect(buildGraphElements(null)).toEqual({ nodes: [], edges: [] })
  })

  it('maps nodes and keeps edges with valid endpoints', () => {
    const graph = {
      nodes: [
        { id: 'a', path: 'src/a.ts', risk: 1, label: 'A' },
        { id: 'b', path: 'src/b.ts', risk: 9 },
      ],
      edges: [
        { source: 'a', target: 'b', kind: 'import' },
        { source: 'a', target: 'missing' }, // dropped: target not a node
      ],
      meta: {},
    } as unknown as GraphData

    const { nodes, edges } = buildGraphElements(graph)
    expect(nodes).toHaveLength(2)
    // label falls back to path when absent
    expect(nodes.find((n) => n.data!.path === 'src/b.ts')!.data!.label).toBe('src/b.ts')
    // only the fully-resolvable edge survives
    expect(edges).toHaveLength(1)
    expect(edges[0].data!.source).toBeTruthy()
    expect(edges[0].data!.target).toBeTruthy()
  })

  it('tags the highest-risk node with glow/important classes', () => {
    const graph = {
      nodes: [
        { id: 'low', path: 'low.ts', risk: 0 },
        { id: 'high', path: 'high.ts', risk: 100 },
      ],
      edges: [],
      meta: {},
    } as unknown as GraphData

    const { nodes } = buildGraphElements(graph)
    const high = nodes.find((n) => n.data!.path === 'high.ts')!
    expect(String(high.classes)).toContain('cs-important')
    expect(String(high.classes)).toContain('cs-glow')
  })
})
