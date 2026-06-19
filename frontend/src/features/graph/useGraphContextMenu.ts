import { useEffect, useRef, useState } from 'react'
import type { MutableRefObject } from 'react'
import type { NodeContextMenuPayload } from './useCytoscapeGraph'
import { clamp } from './GraphCanvas.helpers'

type Params = {
  /** Ref to the graph root element, used to clamp the menu within bounds. */
  rootRef: MutableRefObject<HTMLDivElement | null>
}

/**
 * Owns the node context-menu and file-button overlay state plus their
 * dismissal/positioning effects (outside-click, Escape, in-bounds clamp).
 * Extracted verbatim from GraphCanvas. The file-button measurement/position
 * effect stays in GraphCanvas (it needs the cytoscape container) and consumes
 * the refs/state returned here.
 */
export function useGraphContextMenu({ rootRef }: Params) {
  const [ctxMenu, setCtxMenu] = useState<null | { path: string; x: number; y: number }>(null)
  const [fileButtonPos, setFileButtonPos] = useState<null | { x: number; y: number }>(null)
  const ctxMenuRef = useRef<HTMLDivElement | null>(null)
  const fileButtonsRef = useRef<HTMLDivElement | null>(null)
  const fileButtonsSizeRef = useRef({ width: 0, height: 0 })

  useEffect(() => {
    if (!ctxMenu) return
    const onDown = (e: MouseEvent) => {
      const el = e.target as Node | null
      if (!el) return
      if (ctxMenuRef.current && ctxMenuRef.current.contains(el)) return
      setCtxMenu(null)
    }
    document.addEventListener('mousedown', onDown, true)
    return () => document.removeEventListener('mousedown', onDown, true)
  }, [ctxMenu])

  useEffect(() => {
    if (!ctxMenu) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.preventDefault()
      e.stopImmediatePropagation()
      setCtxMenu(null)
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [ctxMenu])

  useEffect(() => {
    if (!ctxMenu) return
    const t = window.setTimeout(() => {
      const root = rootRef.current
      const menu = ctxMenuRef.current
      if (!root || !menu) return

      const pad = 12
      const rootRect = root.getBoundingClientRect()
      const menuRect = menu.getBoundingClientRect()

      // x/y are in the same coordinate space as the graph canvas (absolute inside root)
      const maxX = Math.max(pad, rootRect.width - menuRect.width - pad)
      const maxY = Math.max(pad, rootRect.height - menuRect.height - pad)

      const nextX = clamp(ctxMenu.x, pad, maxX)
      const nextY = clamp(ctxMenu.y, pad, maxY)

      if (nextX !== ctxMenu.x || nextY !== ctxMenu.y) {
        setCtxMenu((prev) => (prev ? { ...prev, x: nextX, y: nextY } : prev))
      }
    }, 0)
    return () => window.clearTimeout(t)
  }, [ctxMenu])

  const openNodeMenu = (p: NodeContextMenuPayload) => {
    if (!p.path) return
    setCtxMenu({ path: p.path, x: p.x, y: p.y })
  }

  return {
    ctxMenu,
    setCtxMenu,
    fileButtonPos,
    setFileButtonPos,
    ctxMenuRef,
    fileButtonsRef,
    fileButtonsSizeRef,
    openNodeMenu,
  }
}
