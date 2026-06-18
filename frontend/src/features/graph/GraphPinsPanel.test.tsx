import React from 'react'
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { GraphData } from '@/api'
import { GraphPinsPanel } from './GraphPinsPanel'

const graph = {
  nodes: [
    { path: 'src/a.ts', id: 'src/a.ts', risk: 2.0, loc: 100, fan_in: 1, fan_out: 2 },
    { path: 'src/b.ts', id: 'src/b.ts', risk: 0.5, loc: 40, fan_in: 3, fan_out: 1 },
  ],
  edges: [],
} as unknown as GraphData

const baseProps = {
  graph,
  selectedPath: null,
  compactMode: false,
  hoverRevealBlock: '',
  label: (icon: React.ReactNode) => <>{icon}</>,
  onGoTo: () => {},
  onUnpin: () => {},
  onClearPins: () => {},
}

describe('GraphPinsPanel', () => {
  it('renders nothing when there are no pins', () => {
    expect(renderToStaticMarkup(<GraphPinsPanel {...baseProps} pinnedPaths={[]} />)).toBe('')
  })

  it('lists pinned files with their metrics', () => {
    const html = renderToStaticMarkup(<GraphPinsPanel {...baseProps} pinnedPaths={['src/a.ts']} />)
    expect(html).toContain('Pinned (1/3)')
    expect(html).toContain('a.ts') // baseName
    expect(html).toContain('2.00') // risk.toFixed(2)
    expect(html).toContain('100') // loc
  })

  it('renders the compare section once two or more files are pinned', () => {
    const html = renderToStaticMarkup(
      <GraphPinsPanel {...baseProps} pinnedPaths={['src/a.ts', 'src/b.ts']} />,
    )
    expect(html).toContain('Pinned (2/3)')
    expect(html).toContain('Compare')
    expect(html).toContain('ΔRisk')
  })
})
