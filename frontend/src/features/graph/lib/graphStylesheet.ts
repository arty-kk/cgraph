import { riskColor } from '@/shared/lib/riskColor'
import {
  DIM_EDGE_OPACITY,
  DIM_NODE_OPACITY,
  LOCK_BORDER,
  PINNED_BORDER,
  STRONG_EDGE_OPACITY,
  toFiniteNumber,
  nodeSizeFromRisk,
} from './useCytoscapeGraph.constants'

/**
 * Static cytoscape stylesheet for the graph, parameterized only by the edge
 * direction highlight colors. Extracted verbatim from useCytoscapeGraph.
 */
export function buildStylesheet(edgeDirInColor: string, edgeDirOutColor: string): any[] {
  return [
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
  ]
}
