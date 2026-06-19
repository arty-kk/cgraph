import { useEffect } from 'react'
import type { Dispatch, MutableRefObject, SetStateAction } from 'react'
import type { CytoscapeGraphActions } from './useCytoscapeGraph'
import { clamp } from '../lib/GraphCanvas.helpers'

type Pos = { x: number; y: number }

type Params = {
  selectedPath: string | null
  selectedInGraph: boolean
  instanceId: number
  leftPanelOpen: boolean
  rightPanelOpen: boolean
  focusGraph: boolean
  actionsRef: MutableRefObject<CytoscapeGraphActions | null>
  rootRef: MutableRefObject<HTMLDivElement | null>
  containerRef: MutableRefObject<HTMLDivElement | null>
  fileButtonsRef: MutableRefObject<HTMLDivElement | null>
  fileButtonsSizeRef: MutableRefObject<{ width: number; height: number }>
  setFileButtonPos: Dispatch<SetStateAction<Pos | null>>
}

/**
 * Tracks the selected node's rendered position on every animation frame and
 * keeps the floating file/summary buttons anchored to it (clamped within the
 * graph bounds). Extracted verbatim from GraphCanvas.
 */
export function useGraphFileButtonPosition({
  selectedPath,
  selectedInGraph,
  instanceId,
  leftPanelOpen,
  rightPanelOpen,
  focusGraph,
  actionsRef,
  rootRef,
  containerRef,
  fileButtonsRef,
  fileButtonsSizeRef,
  setFileButtonPos,
}: Params) {
  useEffect(() => {
    let raf = 0
    let alive = true

    const tick = () => {
      if (!alive) return
      const path = selectedPath
      if (!path || !selectedInGraph) {
        setFileButtonPos(null)
        return
      }
      const next = actionsRef.current?.getRenderedPosition?.(path)
      const root = rootRef.current
      const container = containerRef.current
      if (!root || !container) {
        setFileButtonPos(null)
        return
      }
      const rootRect = root.getBoundingClientRect()
      const containerRect = container.getBoundingClientRect()
      const buttonsRect = fileButtonsRef.current?.getBoundingClientRect()
      if (buttonsRect && Number.isFinite(buttonsRect.width) && Number.isFinite(buttonsRect.height)) {
        fileButtonsSizeRef.current = { width: buttonsRect.width, height: buttonsRect.height }
      }
      if (next && Number.isFinite(next.x) && Number.isFinite(next.y)) {
        const baseX = next.x + (containerRect.left - rootRect.left)
        const baseY = next.y + (containerRect.top - rootRect.top)
        const x = baseX + 14
        const y = baseY - 14
        const { width: buttonWidth, height: buttonHeight } = fileButtonsSizeRef.current
        const pad = 8
        const minX = pad + buttonWidth / 2
        const minY = pad + buttonHeight / 2
        const maxX = Math.max(minX, rootRect.width - buttonWidth / 2 - pad)
        const maxY = Math.max(minY, rootRect.height - buttonHeight / 2 - pad)
        const nextX = clamp(x, minX, maxX)
        const nextY = clamp(y, minY, maxY)
        setFileButtonPos((prev) => {
          if (!prev) return { x: nextX, y: nextY }
          if (Math.abs(prev.x - nextX) > 0.5 || Math.abs(prev.y - nextY) > 0.5) {
            return { x: nextX, y: nextY }
          }
          return prev
        })
      } else {
        setFileButtonPos(null)
      }
      raf = window.requestAnimationFrame(tick)
    }

    if (selectedPath && selectedInGraph) {
      raf = window.requestAnimationFrame(tick)
    } else {
      setFileButtonPos(null)
    }

    return () => {
      alive = false
      if (raf) window.cancelAnimationFrame(raf)
    }
  }, [selectedPath, selectedInGraph, instanceId, leftPanelOpen, rightPanelOpen, focusGraph])
}
