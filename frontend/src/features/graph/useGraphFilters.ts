import { useEffect, useRef, useState } from 'react'
import type { GraphFilters, LabelMode } from './useCytoscapeGraph'
import { safeStorageSet } from '@/shared/lib/storage'
import {
  FILTER_STORAGE_KEY,
  LABELS_STORAGE_KEY,
  SPOTLIGHT_STORAGE_KEY,
  EDGE_DIR_STORAGE_KEY,
  pidKey,
  loadFilters,
  loadLabelMode,
  loadSpotlight,
  loadEdgeDir,
} from './GraphCanvas.storage'

/**
 * Owns per-project graph UI settings (filters, label mode, spotlight, edge
 * direction colors) and their localStorage persistence. Extracted verbatim
 * from GraphCanvas; the persistence effects are guarded by an internal
 * "booting" ref so loading a project's saved settings does not immediately
 * re-persist them.
 */
export function useGraphFilters(projectId: number | null) {
  const uiBootingRef = useRef(false)

  const [filters, setFilters] = useState<GraphFilters>(() => loadFilters(projectId))
  const [labelMode, setLabelMode] = useState<LabelMode>(() => loadLabelMode(projectId))
  const [spotlight, setSpotlight] = useState<boolean>(() => loadSpotlight(projectId))
  const [edgeDirColors, setEdgeDirColors] = useState<boolean>(() => loadEdgeDir(projectId))

  // Load per-project UI settings when project changes (skip persistence during boot)
  useEffect(() => {
    const pid = Number(projectId)
    if (!Number.isFinite(pid) || pid <= 0) return
    uiBootingRef.current = true

    setFilters(loadFilters(pid))
    setLabelMode(loadLabelMode(pid))
    setSpotlight(loadSpotlight(pid))
    setEdgeDirColors(loadEdgeDir(pid))

    const t = window.setTimeout(() => { uiBootingRef.current = false }, 0)
    return () => window.clearTimeout(t)
  }, [projectId])

  // Persist per-project UI settings (debounced-by-react; guarded by uiBootingRef)
  useEffect(() => {
    if (uiBootingRef.current) return
    const pid = Number(projectId)
    const key = pidKey(FILTER_STORAGE_KEY, Number.isFinite(pid) && pid > 0 ? pid : null)
    safeStorageSet(key, JSON.stringify(filters))
  }, [filters, projectId])

  useEffect(() => {
    if (uiBootingRef.current) return
    const pid = Number(projectId)
    const key = pidKey(LABELS_STORAGE_KEY, Number.isFinite(pid) && pid > 0 ? pid : null)
    safeStorageSet(key, labelMode)
  }, [labelMode, projectId])

  useEffect(() => {
    if (uiBootingRef.current) return
    const pid = Number(projectId)
    const key = pidKey(SPOTLIGHT_STORAGE_KEY, Number.isFinite(pid) && pid > 0 ? pid : null)
    safeStorageSet(key, spotlight ? '1' : '0')
  }, [spotlight, projectId])

  useEffect(() => {
    if (uiBootingRef.current) return
    const pid = Number(projectId)
    const key = pidKey(EDGE_DIR_STORAGE_KEY, Number.isFinite(pid) && pid > 0 ? pid : null)
    safeStorageSet(key, edgeDirColors ? '1' : '0')
  }, [edgeDirColors, projectId])

  return {
    filters,
    setFilters,
    labelMode,
    setLabelMode,
    spotlight,
    setSpotlight,
    edgeDirColors,
    setEdgeDirColors,
  }
}
