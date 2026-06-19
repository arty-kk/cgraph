import React from 'react'
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { CytoscapeGraphActions } from '../hooks/useCytoscapeGraph'
import { GraphStatusBar } from './GraphStatusBar'

const noopActions = {} as unknown as CytoscapeGraphActions

const baseProps = {
  graphMode: 'full' as const,
  visibleNodes: 12,
  returnedNodes: 20,
  returnedEdges: 34,
  selectedPath: null,
  editStats: { hidden: 0, locked: 0 } as ReturnType<CytoscapeGraphActions['getEditStats']>,
  filtersActiveCount: 0,
  compactMode: false,
  hoverRevealFlex: 'flex',
  btnClass: 'btn',
  label: (icon: React.ReactNode) => <>{icon}</>,
  actions: noopActions,
  onOpenPanel: () => {},
  pushUndo: () => {},
  notifyInfo: () => {},
  saveLayout: () => {},
  resetLayout: () => {},
}

describe('GraphStatusBar', () => {
  it('renders nothing without an active project', () => {
    expect(renderToStaticMarkup(<GraphStatusBar {...baseProps} activeProject={null} />)).toBe('')
  })

  it('shows mode, node/edge counts and selection', () => {
    const html = renderToStaticMarkup(
      <GraphStatusBar {...baseProps} activeProject={{ id: 1, name: 'demo' }} selectedPath="src/app/main.ts" />,
    )
    expect(html).toContain('full') // graphMode
    expect(html).toContain('12') // visibleNodes
    expect(html).toContain('20') // returnedNodes
    expect(html).toContain('34') // returnedEdges
    expect(html).toContain('main.ts') // baseName(selectedPath)
  })

  it('renders the filters active-count badge', () => {
    const html = renderToStaticMarkup(
      <GraphStatusBar {...baseProps} activeProject={{ id: 1, name: 'demo' }} filtersActiveCount={3} />,
    )
    expect(html).toContain('3')
  })
})
