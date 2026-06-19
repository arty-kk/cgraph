import { useEffect, useMemo, useRef } from 'react'
import type { MutableRefObject } from 'react'
import type { GraphData, Project } from '@/api'
import type { CytoscapeGraphActions, GraphEditSnapshot } from './useCytoscapeGraph'
import { safeStorageGet } from '@/shared/lib/storage'

type Params = {
  activeProject: Project | null
  graphMode: 'local' | 'full' | 'limit'
  selectedPath: string | null
  graph: GraphData | null
  instanceId: number
  actions: CytoscapeGraphActions
  actionsRef: MutableRefObject<CytoscapeGraphActions | null>
  notifyInfo: (msg: string) => void
  notifyRef: MutableRefObject<(msg: string) => void>
  pushUndo: (snap: GraphEditSnapshot | null) => void
}

/**
 * Per-project/per-mode saved graph layout: derives the storage key, loads a
 * saved layout once per instance when one exists, and exposes save/reset
 * actions. Extracted verbatim from GraphCanvas.
 */
export function useGraphLayout({
  activeProject,
  graphMode,
  selectedPath,
  graph,
  instanceId,
  actions,
  actionsRef,
  notifyInfo,
  notifyRef,
  pushUndo,
}: Params) {
  const layoutKey = useMemo(() => {
    const pid = activeProject?.id != null ? String(activeProject.id) : 'none'
    const localSel = graphMode === 'local' ? (selectedPath || 'none') : 'global'
    return `cs.layout.v1.${pid}.${graphMode}.${localSel}`
  }, [activeProject?.id, graphMode, selectedPath])
  const loadedLayoutKeyRef = useRef<string | null>(null)

  useEffect(() => {
    if (!graph || !activeProject) return
    const applyKey = `${layoutKey}::${instanceId}`
    if (loadedLayoutKeyRef.current === applyKey) return
    const has = Boolean(safeStorageGet(layoutKey))
    if (!has) {
      loadedLayoutKeyRef.current = applyKey
      return
    }
    actions.loadLayout(layoutKey, { onApplied: () => notifyInfo('Layout loaded') })
    loadedLayoutKeyRef.current = applyKey
  }, [actions, activeProject, graph, instanceId, layoutKey, notifyInfo])

  const saveLayout = () => {
    const a = actionsRef.current
    if (!a) return
    const ok = a.saveLayout(layoutKey)
    notifyRef.current(ok ? 'Layout saved' : 'Layout save failed')
  }
  const resetLayout = () => {
    const a = actionsRef.current
    if (!a) return
    pushUndo(a.exportSnapshot())
    a.clearLayout(layoutKey)
    a.relayout()
    notifyRef.current('Layout reset')
  }

  return { saveLayout, resetLayout }
}
