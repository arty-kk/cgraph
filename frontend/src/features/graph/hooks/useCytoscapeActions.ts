import { useCallback } from 'react'
import type { MutableRefObject } from 'react'
import type { Core } from 'cytoscape'
import { safeStorageGet, safeStorageRemove, safeStorageSet } from '@/shared/lib/storage'
import {
  DEFAULT_LAYOUT,
  CENTER_RETRY_ATTEMPTS,
  CENTER_RETRY_DELAY_MS,
  safeStr,
} from '../lib/useCytoscapeGraph.constants'
import type { GraphEditSnapshot } from '../lib/useCytoscapeGraph.constants'

type Params = {
  cyRef: MutableRefObject<Core | null>
  hiddenKeysRef: MutableRefObject<Set<string>>
  lockedKeysRef: MutableRefObject<Set<string>>
  applyFiltersRef: MutableRefObject<() => void>
  animateCenterTo: (eles: any) => void
  isHiddenNode: (n: any) => boolean | ''
}

/**
 * Imperative actions over the live cytoscape instance: viewport (fit/relayout/
 * center), queries (match/neighbors/next), visibility + lock editing, and
 * snapshot/layout persistence. Extracted verbatim from useCytoscapeGraph; all
 * callbacks close over the passed refs/helpers exactly as before.
 */
export function useCytoscapeActions({
  cyRef,
  hiddenKeysRef,
  lockedKeysRef,
  applyFiltersRef,
  animateCenterTo,
  isHiddenNode,
}: Params) {
  const fit = useCallback(() => {
    try {
      const cy = cyRef.current
      if (!cy) return
      const visible = cy.elements(':visible')
      if (visible && !visible.empty()) cy.fit(visible, 60)
      else cy.fit(undefined, 60)
    } catch {}
  }, [])

  const relayout = useCallback(() => {
    try {
      const cy = cyRef.current
      if (!cy) return
      const layout: any = cy.layout(DEFAULT_LAYOUT)
      layout.on('layoutstop', () => {
        try {
          cy.fit(cy.elements(':visible'), 60)
        } catch {}
      })
      layout.run()
    } catch {}
  }, [])

  const centerSelected = useCallback(() => {
    try {
      const cy = cyRef.current
      if (!cy) return
      const sel = cy.nodes(':selected')
      if (!sel || sel.empty()) return
      const centerTarget = sel.closedNeighborhood()
      const visibleTarget = centerTarget.filter(':visible')
      animateCenterTo(visibleTarget.empty() ? sel : visibleTarget)
    } catch {}
  }, [animateCenterTo])

  const centerPath = useCallback(
    (path: string) => {
      const p = safeStr(path)
      if (!p) return

      let attempt = 0
      const tryCenter = () => {
        const cy = cyRef.current
        if (!cy) return
        const match = cy.nodes().filter((n) => n.data('path') === p || n.id() === p)
        if (match && !match.empty()) {
          const centerTarget = match.closedNeighborhood()
          const visibleTarget = centerTarget.filter(':visible')
          animateCenterTo(visibleTarget.empty() ? match : visibleTarget)
          return
        }
        attempt += 1
        if (attempt < CENTER_RETRY_ATTEMPTS) {
          window.setTimeout(tryCenter, CENTER_RETRY_DELAY_MS)
        }
      }

      tryCenter()
    },
    [animateCenterTo],
  )

  const getMatch = useCallback((path: string) => {
    const cy = cyRef.current
    if (!cy) return null
    const p = safeStr(path)
    if (!p) return null
    const match = cy.nodes().filter((n) => n.data('path') === p || n.id() === p)
    return match && !match.empty() ? match : null
  }, [])

  const getRenderedPosition = useCallback((path: string) => {
    const cy = cyRef.current
    if (!cy) return null
    const p = safeStr(path)
    if (!p) return null
    const match = cy.nodes().filter((n) => n.data('path') === p || n.id() === p)
    if (!match || match.empty()) return null
    const pos = match[0].renderedPosition()
    if (!pos || !Number.isFinite(pos.x) || !Number.isFinite(pos.y)) return null
    return { x: Number(pos.x), y: Number(pos.y) }
  }, [])

  const getNeighbors = useCallback((path: string) => {
    const cy = cyRef.current
    if (!cy) return { inbound: [], outbound: [] }
    const p = safeStr(path)
    if (!p) return { inbound: [], outbound: [] }
    const inbound = new Set<string>()
    const outbound = new Set<string>()
    cy.edges().forEach((edge: any) => {
      const source = edge.source?.()
      const target = edge.target?.()
      if (!source || !target) return
      const sourcePath = safeStr(source.data?.('path'))
      const targetPath = safeStr(target.data?.('path'))
      const sourceId = safeStr(source.id?.())
      const targetId = safeStr(target.id?.())
      const sourceKey = safeStr(sourcePath || sourceId)
      const targetKey = safeStr(targetPath || targetId)
      const isSourceMatch = sourcePath === p || sourceId === p
      const isTargetMatch = targetPath === p || targetId === p
      if (isSourceMatch && targetKey) outbound.add(targetKey)
      if (isTargetMatch && sourceKey) inbound.add(sourceKey)
    })
    const sortKeys = (items: Set<string>) => Array.from(items).sort((a, b) => a.localeCompare(b))
    return { inbound: sortKeys(inbound), outbound: sortKeys(outbound) }
  }, [])

  const getNextNode = useCallback((path: string, opts?: { loop?: boolean }) => {
    const cy = cyRef.current
    if (!cy) return null
    const p = safeStr(path)
    if (!p) return null
    const nodes = cy.nodes(':visible')
    if (!nodes || nodes.empty()) return null
    const sorted = nodes.toArray().sort((a: any, b: any) => {
      const aKey = safeStr(a.data?.('path') || a.id?.())
      const bKey = safeStr(b.data?.('path') || b.id?.())
      return aKey.localeCompare(bKey)
    })
    const currentIndex = sorted.findIndex((n: any) => {
      const nPath = safeStr(n.data?.('path'))
      const nId = safeStr(n.id?.())
      return nPath === p || nId === p
    })
    if (currentIndex === -1) return null
    const nextIndex = currentIndex + 1
    if (nextIndex >= sorted.length) {
      if (opts?.loop) {
        const first = sorted[0]
        return safeStr(first.data?.('path') || first.id?.()) || null
      }
      return null
    }
    const nextNode = sorted[nextIndex]
    return safeStr(nextNode.data?.('path') || nextNode.id?.()) || null
  }, [])

  const hidePath = useCallback(
    (path: string) => {
      const cy = cyRef.current
      if (!cy) return
      const match = getMatch(path)
      if (!match) return
      match.forEach((n: any) => {
        const id = safeStr(n.id())
        const p = safeStr(n.data('path'))
        const key = safeStr(p || id)
        if (id) hiddenKeysRef.current.add(id)
        if (p) hiddenKeysRef.current.add(p)
        if (key) hiddenKeysRef.current.add(key)
      })
      applyFiltersRef.current()
    },
    [getMatch],
  )

  const showPath = useCallback(
    (path: string) => {
      const cy = cyRef.current
      if (!cy) return
      const match = getMatch(path)
      if (!match) return
      match.forEach((n: any) => {
        const id = safeStr(n.id())
        const p = safeStr(n.data('path'))
        const key = safeStr(p || id)
        if (id) hiddenKeysRef.current.delete(id)
        if (p) hiddenKeysRef.current.delete(p)
        if (key) hiddenKeysRef.current.delete(key)
      })
      applyFiltersRef.current()
    },
    [getMatch],
  )

  const showAll = useCallback(() => {
    hiddenKeysRef.current = new Set()
    applyFiltersRef.current()
  }, [])

  const hideOthers = useCallback(
    (path: string) => {
      const cy = cyRef.current
      if (!cy) return
      const match = getMatch(path)
      if (!match) return
      const keep = match.closedNeighborhood().nodes()
      cy.nodes().forEach((n: any) => {
        if (keep.contains(n)) return
        const id = safeStr(n.id())
        const p = safeStr(n.data('path'))
        const key = safeStr(p || id)
        if (id) hiddenKeysRef.current.add(id)
        if (p) hiddenKeysRef.current.add(p)
        if (key) hiddenKeysRef.current.add(key)
      })
      applyFiltersRef.current()
    },
    [getMatch],
  )

  const toggleLockPath = useCallback(
    (path: string) => {
      const cy = cyRef.current
      if (!cy) return
      const match = getMatch(path)
      if (!match) return
      match.forEach((n: any) => {
        const id = safeStr(n.id())
        const p = safeStr(n.data('path'))
        const key = safeStr(p || id)
        const isLocked = (id && lockedKeysRef.current.has(id)) || (p && lockedKeysRef.current.has(p)) || (key && lockedKeysRef.current.has(key))
        if (isLocked) {
          if (id) lockedKeysRef.current.delete(id)
          if (p) lockedKeysRef.current.delete(p)
          if (key) lockedKeysRef.current.delete(key)
          try { n.unlock() } catch {}
        } else {
          if (id) lockedKeysRef.current.add(id)
          if (p) lockedKeysRef.current.add(p)
          if (key) lockedKeysRef.current.add(key)
          try { n.lock() } catch {}
        }
      })
      applyFiltersRef.current()
    },
    [getMatch],
  )

  const unlockAll = useCallback(() => {
    const cy = cyRef.current
    if (!cy) return
    lockedKeysRef.current = new Set()
    try {
      cy.nodes().unlock()
    } catch {}
    applyFiltersRef.current()
  }, [])

  const relayoutVisible = useCallback(() => {
    try {
      const cy = cyRef.current
      if (!cy) return
      const visible = cy.elements(':visible')
      const layout: any = visible.layout(DEFAULT_LAYOUT as any)
      layout.on('layoutstop', () => {
        try { cy.fit(cy.elements(':visible'), 60) } catch {}
      })
      layout.run()
    } catch {}
  }, [])

  const exportSnapshot = useCallback((opts?: { visibleOnly?: boolean }): GraphEditSnapshot | null => {
    try {
      const cy = cyRef.current
      if (!cy) return null
      const visibleOnly = Boolean(opts?.visibleOnly)
      const positions: Record<string, { x: number; y: number }> = {}
      const nodes = visibleOnly ? cy.nodes(':visible') : cy.nodes()
      nodes.forEach((n: any) => {
        const id = safeStr(n.id())
        const pos = n.position()
        if (!id || !pos) return
        if (!Number.isFinite(pos.x) || !Number.isFinite(pos.y)) return
        positions[id] = { x: Number(pos.x), y: Number(pos.y) }
      })
      const z = cy.zoom()
      const p = cy.pan()
      return {
        version: 1,
        zoom: Number.isFinite(Number(z)) ? Number(z) : 1,
        pan: { x: Number.isFinite(Number(p?.x)) ? Number(p.x) : 0, y: Number.isFinite(Number(p?.y)) ? Number(p.y) : 0 },
        positions,
        hiddenKeys: Array.from(hiddenKeysRef.current),
        lockedKeys: Array.from(lockedKeysRef.current),
      }
    } catch {
      return null
    }
  }, [])

  const applySnapshot = useCallback((snap: GraphEditSnapshot): boolean => {
    try {
      const cy = cyRef.current
      if (!cy || !snap || snap.version !== 1) return false

      hiddenKeysRef.current = new Set((snap.hiddenKeys || []).map((x) => safeStr(x)).filter(Boolean))
      lockedKeysRef.current = new Set((snap.lockedKeys || []).map((x) => safeStr(x)).filter(Boolean))

      const pos = snap.positions || {}
      cy.batch(() => {
        cy.nodes().forEach((n: any) => {
          const id = safeStr(n.id())
          const p = pos[id]
          if (!p) return
          if (!Number.isFinite(p.x) || !Number.isFinite(p.y)) return
          try { n.position({ x: p.x, y: p.y }) } catch {}
        })
      })

      applyFiltersRef.current()
      try { cy.zoom(snap.zoom) } catch {}
      try { cy.pan(snap.pan as any) } catch {}
      return true
    } catch {
      return false
    }
  }, [])

  const saveLayout = useCallback((storageKey: string): boolean => {
    try {
      const key = safeStr(storageKey)
      if (!key) return false
      const snap = exportSnapshot()
      if (!snap) return false
      safeStorageSet(key, JSON.stringify(snap))
      return true
    } catch {
      return false
    }
  }, [exportSnapshot])

  const clearLayout = useCallback((storageKey: string) => {
    try {
      const key = safeStr(storageKey)
      if (!key) return
      safeStorageRemove(key)
    } catch {}
  }, [])

  const loadLayout = useCallback(
    (
      storageKey: string,
      opts?: { attempts?: number; onApplied?: () => void }
    ): boolean => {
    try {
      const key = safeStr(storageKey)
      if (!key) return false
      const raw = safeStorageGet(key)
      if (!raw) return false
      const parsed = JSON.parse(raw) as GraphEditSnapshot
      const attempts = Number.isFinite(Number(opts?.attempts)) ? Number(opts?.attempts) : 10
      
      const tryApply = (n: number): boolean => {
        const cy = cyRef.current
        if (!cy) return false
        if (cy.nodes().length === 0 && n > 0) {
          window.setTimeout(() => tryApply(n - 1), 80)
          return true
        }
        applySnapshot(parsed)
        try { 
          opts?.onApplied?.() 
        } catch {}
        return true
      }
      return tryApply(attempts)
    } catch {
      return false
    }
  }, [applySnapshot])

  const getEditStats = useCallback(() => {
    try {
      const cy = cyRef.current
      if (!cy) return { hidden: 0, locked: 0 }
      let hidden = 0
      let locked = 0
      cy.nodes().forEach((n: any) => {
        if (isHiddenNode(n)) hidden += 1
        const id = safeStr(n.id())
        const path = safeStr(n.data('path'))
        const key = safeStr(path || id)
        const isLocked = (id && lockedKeysRef.current.has(id)) || (path && lockedKeysRef.current.has(path)) || (key && lockedKeysRef.current.has(key))
        if (isLocked) locked += 1
      })
      return { hidden, locked }
    } catch {
      return { hidden: 0, locked: 0 }
    }
  }, [isHiddenNode])

  const resize = useCallback(() => {
    try {
      const cy = cyRef.current
      if (!cy) return
      cy.resize()
    } catch {}
  }, [])

  return {
    resize,
    fit,
    relayout,
    relayoutVisible,
    centerSelected,
    centerPath,
    getRenderedPosition,
    getNeighbors,
    getNextNode,
    hidePath,
    hideOthers,
    showPath,
    showAll,
    toggleLockPath,
    unlockAll,
    exportSnapshot,
    applySnapshot,
    saveLayout,
    loadLayout,
    clearLayout,
    getEditStats,
  }
}
