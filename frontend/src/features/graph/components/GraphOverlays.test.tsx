import React from 'react'
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { GraphData, Project } from '@/api'
import {
  GraphLoadingBanner,
  GraphLimitBanner,
  GraphEmptyState,
  GraphFileButtons,
} from './GraphOverlays'

const project = { id: 1, name: 'demo' } as Project
const graph = { nodes: [], edges: [], meta: {} } as unknown as GraphData

describe('GraphLoadingBanner', () => {
  it('renders nothing when not hydrating', () => {
    expect(renderToStaticMarkup(<GraphLoadingBanner hydrating={false} pinnedCount={0} compactMode={false} />)).toBe('')
  })
  it('renders the batch-loading message when hydrating', () => {
    const html = renderToStaticMarkup(<GraphLoadingBanner hydrating pinnedCount={0} compactMode={false} />)
    expect(html).toContain('Loading a large graph in batches')
  })
})

describe('GraphLimitBanner', () => {
  it('renders nothing when show is false', () => {
    const html = renderToStaticMarkup(
      <GraphLimitBanner show={false} activeProject={project} truncated={false} limitNodes={null} returnedNodes={0} totalNodes={null} compactMode={false} hoverRevealBlock="" />,
    )
    expect(html).toBe('')
  })
  it('shows truncated state with node counts', () => {
    const html = renderToStaticMarkup(
      <GraphLimitBanner show activeProject={project} truncated limitNodes={null} returnedNodes={50} totalNodes={200} compactMode={false} hoverRevealBlock="" />,
    )
    expect(html).toContain('Truncated')
    expect(html).toContain('50/200')
  })
  it('shows top-N limited state', () => {
    const html = renderToStaticMarkup(
      <GraphLimitBanner show activeProject={project} truncated={false} limitNodes={30} returnedNodes={30} totalNodes={null} compactMode={false} hoverRevealBlock="" />,
    )
    expect(html).toContain('Limited')
    expect(html).toContain('top-N=30')
  })
})

describe('GraphEmptyState', () => {
  const noop = () => {}
  it('renders nothing once a graph is present', () => {
    const html = renderToStaticMarkup(
      <GraphEmptyState activeProject={project} graph={graph} busy={false} graphMode="full" selectedPath={null} onOpenPalette={noop} onScan={noop} onRefresh={noop} />,
    )
    expect(html).toBe('')
  })
  it('prompts to pick a file in local mode with no selection', () => {
    const html = renderToStaticMarkup(
      <GraphEmptyState activeProject={project} graph={null} busy={false} graphMode="local" selectedPath={null} onOpenPalette={noop} onScan={noop} onRefresh={noop} />,
    )
    expect(html).toContain('Graph is not displayed yet')
    expect(html).toContain('Pick File')
  })
})

describe('GraphFileButtons', () => {
  const noop = () => {}
  const base = {
    selectedPath: 'src/a.ts',
    activeProject: project,
    selectedInGraph: true,
    fileButtonsRef: { current: null },
    onOpenFileEditor: noop,
    onQuickSummary: noop,
    quickSummaryTitleFor: () => 'Quick summary',
    isQuickSummaryDisabledFor: () => false,
  }
  it('renders nothing without a position', () => {
    expect(renderToStaticMarkup(<GraphFileButtons {...base} fileButtonPos={null} />)).toBe('')
  })
  it('renders view + summary buttons when positioned', () => {
    const html = renderToStaticMarkup(<GraphFileButtons {...base} fileButtonPos={{ x: 10, y: 20 }} />)
    expect(html).toContain('View/edit file')
    expect(html).toContain('Quick summary')
  })
})
