import type { LayoutOptions } from 'cytoscape'

export type GraphFilters = {
  text: string
  minRisk: number
  onlySelectionNeighborhood: boolean
}

export type GraphStats = {
  totalNodes: number
  visibleNodes: number
  hydrating: boolean
}

export type LabelMode = 'auto' | 'on' | 'off'

export type EdgeDirectionHighlight = {
  enabled: boolean
  inColor: string
  outColor: string
}

export type NodeContextMenuPayload = {
  path: string
  x: number
  y: number
}

export type GraphEditSnapshot = {
  version: 1
  zoom: number
  pan: { x: number; y: number }
  positions: Record<string, { x: number; y: number }> // by node id
  hiddenKeys: string[]
  lockedKeys: string[]
}

export type GraphEditEvent =
  | { kind: 'dragstart' }
  | { kind: 'dragend' }

export const DEFAULT_LAYOUT: LayoutOptions = ({
  name: 'cose',
  animate: false,
  fit: false,
  padding: 80,
  randomize: true,
  componentSpacing: 140,
  nodeOverlap: 10,
  nodeRepulsion: 20000,
  idealEdgeLength: 320,
  edgeElasticity: 0.35,
  gravity: 0.18,
  numIter: 1800,
  initialTemp: 250,
  coolingFactor: 0.95,
  minTemp: 1.0,
} as any)

export const BATCH_SIZE = 400
export const DIM_NODE_OPACITY = 0.08
export const DIM_EDGE_OPACITY = 0.05
export const STRONG_EDGE_OPACITY = 0.75
export const PINNED_BORDER = '#a855f7'
export const LABEL_ZOOM_THRESHOLD = 1.15
export const MAX_NEIGHBOR_LABELS = 28
export const EDGE_BATCH_SIZE = 1600
export const DOUBLE_TAP_MS = 320

export const CENTER_MIN_ZOOM = 0.6
export const CENTER_MAX_ZOOM = 2.5
export const CENTER_RETRY_ATTEMPTS = 60
export const CENTER_RETRY_DELAY_MS = 80

export const GRID_SPACING = 90
export const LOCK_BORDER = '#93c5fd'
export const NODE_SIZE_MIN = 14
export const NODE_SIZE_MAX = 28

export const STAR_ARC_PAD = Math.PI * 0.15 // отступ от краёв полуокружности
export const STAR_BASE_RADIUS_IN = 100
export const STAR_BASE_RADIUS_OUT = 150
export const STAR_RING_SPACING = 34
export const STAR_MAX_NEIGHBORS = 180 // чтобы не пытаться “взрывать” тысячи связей
export const STAR_ANIMATE_MAX = 80 // анимацию делаем только если соседей немного

export function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v))
}

export function safeStr(v: unknown): string {
  if (v == null) return ''
  const s = typeof v === 'string' ? v : String(v)
  return s.trim()
}

export function toFiniteNumber(v: unknown, fallback = 0): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}

export function nodeSizeFromRisk(risk: unknown): number {
  const v = Math.max(0, toFiniteNumber(risk, 0))
  const t = 1 - Math.exp(-v / 18)
  return clamp(NODE_SIZE_MIN + (NODE_SIZE_MAX - NODE_SIZE_MIN) * t, NODE_SIZE_MIN, NODE_SIZE_MAX)
}

export function makeUniqueId(base: string, used: Set<string>): string {
  const b = base || 'node'
  let id = b
  let i = 2
  while (used.has(id)) {
    id = `${b}#${i}`
    i += 1
  }
  used.add(id)
  return id
}
