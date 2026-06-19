import React from 'react'
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { GraphData, Project } from '@/api'
import type { CytoscapeGraphActions, GraphEditSnapshot } from '../hooks/useCytoscapeGraph'
import type { GraphStats } from '../lib/useCytoscapeGraph.constants'
import { DEFAULT_FILTERS } from '../lib/GraphCanvas.storage'
import { GraphControlPanel, type GraphControlView } from './GraphControlPanel'

const noopActions = {} as unknown as CytoscapeGraphActions

const graph: GraphData = {
  nodes: [
    { id: 'a', path: 'src/a.ts', risk: 2 },
    { id: 'b', path: 'src/b.ts', risk: 5 },
  ],
  edges: [{ source: 'a', target: 'b' }],
  meta: {},
} as unknown as GraphData

const baseView: GraphControlView = {
  graph,
  activeProject: { id: 1, name: 'demo' } as Project,
  busy: false,
  selectedPath: null,
  selectedInGraph: false,
  workspaceView: 'graph',
  focusGraph: false,
  setFocusGraph: () => {},
  panelOpen: false,
  setPanelOpen: () => {},
  neighborsOpen: false,
  setNeighborsOpen: () => {},
  setHelpOpen: () => {},
  panelRef: { current: null },
  filters: DEFAULT_FILTERS,
  setFilters: () => {},
  labelMode: 'auto',
  setLabelMode: () => {},
  spotlight: false,
  setSpotlight: () => {},
  edgeDirColors: false,
  setEdgeDirColors: () => {},
  actions: noopActions,
  stats: { totalNodes: 2, visibleNodes: 2, hydrating: false } as GraphStats,
  neighbors: { inbound: [], outbound: [] },
  selectionTrail: [],
  returnedNodes: 5,
  returnedEdges: 7,
  totalNodes: 5,
  totalEdges: 7,
  limitNodes: null,
  truncated: false,
  isSelectedPinned: false,
  onTogglePinSelected: () => {},
  onToggleWorkspaceView: () => {},
  canGoBack: false,
  canGoForward: false,
  onBack: () => {},
  onForward: () => {},
  goTo: () => {},
  onEscAction: () => {},
  resetFilters: () => {},
  doUndo: () => {},
  doRedo: () => {},
  undoStackRef: { current: [] as GraphEditSnapshot[] },
  redoStackRef: { current: [] as GraphEditSnapshot[] },
  label: (icon: React.ReactNode) => <>{icon}</>,
  btnClass: 'btn',
  toggleBtnClass: 'tbtn',
}

describe('GraphControlPanel', () => {
  it('renders the collapsed toolbar with action buttons', () => {
    const html = renderToStaticMarkup(<GraphControlPanel view={baseView} />)
    expect(html).toContain('<button')
    // Undo/redo buttons (absorbed undoRedoControls) are present and disabled
    // because the stacks are empty.
    expect(html).toContain('Undo (Ctrl/⌘+Z)')
    expect(html).toContain('Redo (Ctrl/⌘+Shift+Z)')
  })

  it('shows the graph info summary when the panel is open', () => {
    const html = renderToStaticMarkup(
      <GraphControlPanel view={{ ...baseView, panelOpen: true }} />,
    )
    expect(html).toContain('5 Nodes · 7 Edges')
  })

  it('renders the empty graph info when no project is selected', () => {
    const html = renderToStaticMarkup(
      <GraphControlPanel view={{ ...baseView, panelOpen: true, activeProject: null }} />,
    )
    expect(html).toContain('Pick a project')
  })
})
