import React from 'react'
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { GraphData } from '@/api'
import type { CytoscapeGraphActions } from '../hooks/useCytoscapeGraph'
import { GraphContextMenu } from './GraphContextMenu'

const noopActions = {} as unknown as CytoscapeGraphActions

const baseProps = {
  menuRef: { current: null },
  ctxNode: null,
  ctxPinned: false,
  selectedPath: null,
  actions: noopActions,
  onClose: () => {},
  onOpenNeighbors: () => {},
  onTogglePinPath: () => {},
  onOpenFileEditor: () => {},
  onQuickSummary: () => {},
  onClearSelection: () => {},
  pushUndo: () => {},
  saveLayout: () => {},
  resetLayout: () => {},
  notifyInfo: () => {},
  quickSummaryTitleFor: () => '',
  isQuickSummaryDisabledFor: () => false,
}

describe('GraphContextMenu', () => {
  it('renders nothing when there is no active menu', () => {
    expect(renderToStaticMarkup(<GraphContextMenu {...baseProps} ctxMenu={null} />)).toBe('')
  })

  it('renders the node path and the action buttons when open', () => {
    const html = renderToStaticMarkup(
      <GraphContextMenu {...baseProps} ctxMenu={{ path: 'src/app/main.ts', x: 10, y: 20 }} />,
    )
    expect(html).toContain('main.ts') // baseName(path)
    expect(html).toContain('src/app/main.ts')
    expect(html).toContain('Center')
    expect(html).toContain('Pin')
    expect(html).toContain('Hide node')
    expect(html).toContain('Copy Path')
    expect(html).toContain('Neighbors')
  })

  it('shows Unpin instead of Pin when the node is pinned', () => {
    const html = renderToStaticMarkup(
      <GraphContextMenu {...baseProps} ctxPinned ctxMenu={{ path: 'a.ts', x: 0, y: 0 }} />,
    )
    expect(html).toContain('Unpin')
  })

  it('renders node metrics when ctxNode is provided', () => {
    const ctxNode = {
      path: 'a.ts',
      id: 'a.ts',
      risk: 1.5,
      loc: 100,
      fan_in: 2,
      fan_out: 3,
    } as unknown as GraphData['nodes'][number]
    const html = renderToStaticMarkup(
      <GraphContextMenu {...baseProps} ctxNode={ctxNode} ctxMenu={{ path: 'a.ts', x: 0, y: 0 }} />,
    )
    expect(html).toContain('1.50') // risk.toFixed(2)
    expect(html).toContain('100') // loc
    expect(html).toContain('2/3') // fan_in/fan_out
  })
})
