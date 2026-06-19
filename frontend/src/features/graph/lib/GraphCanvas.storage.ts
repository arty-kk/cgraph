import type { GraphFilters, LabelMode } from '../hooks/useCytoscapeGraph'
import { safeStorageGet, safeStorageSet } from '@/shared/lib/storage'

export const FILTER_STORAGE_KEY = 'cs.graph.filters.v1'
export const LABELS_STORAGE_KEY = 'cs.graph.labels.v1'
export const SPOTLIGHT_STORAGE_KEY = 'cs.graph.spotlight.v1'
export const EDGE_DIR_STORAGE_KEY = 'cs.graph.edgeDir.v1'
export const EDGE_IN_COLOR = '#22c55e'
export const EDGE_OUT_COLOR = '#3b82f6'
export const LEGACY_FILTER_STORAGE_KEY = 'cs.graph.filters'
export const LEGACY_LABELS_STORAGE_KEY = 'cs.graph.labels'
export const LEGACY_SPOTLIGHT_STORAGE_KEY = 'cs.graph.spotlight'

export const DEFAULT_FILTERS: GraphFilters = {
  text: '',
  minRisk: 0,
  onlySelectionNeighborhood: false,
}

export function pidKey(base: string, pid: number | null): string {
  const n = Number(pid)
  if (Number.isFinite(n) && n > 0) return `${base}.${n}`
  return base
}

export function loadFilters(pid: number | null): GraphFilters {
  const key = pidKey(FILTER_STORAGE_KEY, pid)
  const raw = safeStorageGet(key)
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as Partial<GraphFilters>
      return {
        text: typeof parsed.text === 'string' ? parsed.text : DEFAULT_FILTERS.text,
        minRisk: typeof parsed.minRisk === 'number' ? parsed.minRisk : DEFAULT_FILTERS.minRisk,
        onlySelectionNeighborhood:
          typeof parsed.onlySelectionNeighborhood === 'boolean'
            ? parsed.onlySelectionNeighborhood
            : DEFAULT_FILTERS.onlySelectionNeighborhood,
      }
    } catch {}
  }

  const legacyRaw = safeStorageGet(LEGACY_FILTER_STORAGE_KEY)
  if (legacyRaw) {
    try {
      const parsed = JSON.parse(legacyRaw) as Partial<GraphFilters>
      const out: GraphFilters = {
        text: typeof parsed.text === 'string' ? parsed.text : DEFAULT_FILTERS.text,
        minRisk: typeof parsed.minRisk === 'number' ? parsed.minRisk : DEFAULT_FILTERS.minRisk,
        onlySelectionNeighborhood:
          typeof parsed.onlySelectionNeighborhood === 'boolean'
            ? parsed.onlySelectionNeighborhood
            : DEFAULT_FILTERS.onlySelectionNeighborhood,
      }
      safeStorageSet(key, JSON.stringify(out))
      return out
    } catch {}
  }

  return DEFAULT_FILTERS
}

export function loadLabelMode(pid: number | null): LabelMode {
  const key = pidKey(LABELS_STORAGE_KEY, pid)
  const raw = (safeStorageGet(key, '') || '').trim()
  if (raw === 'on' || raw === 'off' || raw === 'auto') return raw

  const legacy = (safeStorageGet(LEGACY_LABELS_STORAGE_KEY, '') || '').trim()
  if (legacy === 'on' || legacy === 'off' || legacy === 'auto') {
    safeStorageSet(key, legacy)
    return legacy
  }
  return 'auto'
}

export function loadSpotlight(pid: number | null): boolean {
  const key = pidKey(SPOTLIGHT_STORAGE_KEY, pid)
  const raw = (safeStorageGet(key, '') || '').trim()
  if (raw === '0') return false
  if (raw === '1') return true

  const legacy = (safeStorageGet(LEGACY_SPOTLIGHT_STORAGE_KEY, '') || '').trim()
  if (legacy === '0') { safeStorageSet(key, '0'); return false }
  if (legacy === '1') { safeStorageSet(key, '1'); return true }
  return true
}

export function loadEdgeDir(pid: number | null): boolean {
  const key = pidKey(EDGE_DIR_STORAGE_KEY, pid)
  const raw = (safeStorageGet(key, '') || '').trim()
  if (raw === '0') return false
  if (raw === '1') return true
  return true
}
