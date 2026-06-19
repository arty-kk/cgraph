import { useCallback, useMemo } from 'react'
import type { MutableRefObject } from 'react'
import { useWorkspace } from '../workspace'

type Params = {
  PIN_LIMIT: number
  selectedPathRef: MutableRefObject<string | null>
  backStackRef: MutableRefObject<string[]>
  forwardStackRef: MutableRefObject<string[]>
  selectionTrailRef: MutableRefObject<string[]>
  setSelection: (nextRaw: string | null, opts?: { pushHistory?: boolean }) => void
  resetForSelectionChange: () => void
}

/**
 * Selection clear, pin toggles (with PIN_LIMIT), and back/forward history
 * navigation + the graph background-tap clear. Extracted verbatim from
 * useStubGraphApp.
 */
export function useSelectionNav({
  PIN_LIMIT,
  selectedPathRef,
  backStackRef,
  forwardStackRef,
  selectionTrailRef,
  setSelection,
  resetForSelectionChange,
}: Params) {
  const ws = useWorkspace()
  const { selectedPath, pinnedPaths, backStack, forwardStack } = ws.state
  const { setSelectedPath, setPinnedPaths, setBackStack, setForwardStack, setSelectionTrail } =
    ws.setters
  const onClearSelection = useCallback(() => {
    setSelection(null, { pushHistory: true })
  }, [setSelection])

  const isSelectedPinned = useMemo(() => {
    if (!selectedPath) return false
    return pinnedPaths.includes(selectedPath)
  }, [pinnedPaths, selectedPath])

  const togglePinPath = useCallback((path: string) => {
    const p = String(path || '').trim()
    if (!p) return
    setPinnedPaths((prev) => {
      if (prev.includes(p)) return prev.filter((x) => x !== p)
      if (prev.length >= PIN_LIMIT) {
        // Drop oldest pinned
        return [...prev.slice(1), p]
      }
      return [...prev, p]
    })
  }, [])

  const togglePinSelected = useCallback(() => {
    if (!selectedPath) return
    togglePinPath(selectedPath)
  }, [selectedPath, togglePinPath])

  const unpinPath = useCallback((path: string) => {
    const p = String(path || '').trim()
    if (!p) return
    setPinnedPaths((prev) => prev.filter((x) => x !== p))
  }, [])

  const clearPins = useCallback(() => setPinnedPaths([]), [])

  const canGoBack = backStack.length > 0
  const canGoForward = forwardStack.length > 0

  const goBack = useCallback(() => {
    const b = backStackRef.current || []
    if (b.length === 0) return
    const current = selectedPathRef.current
    const prev = b[b.length - 1]

    const nextBack = b.slice(0, -1)
    backStackRef.current = nextBack
    setBackStack(nextBack)

    if (current) {
      const nextFwd = [current, ...(forwardStackRef.current || [])].slice(0, 200)
      forwardStackRef.current = nextFwd
      setForwardStack(nextFwd)
    }

    // trail
    if (prev) {
      const t0 = selectionTrailRef.current || []
      const filtered = t0.filter((p) => p !== prev)
      const t1 = [...filtered, prev].slice(-3)
      selectionTrailRef.current = t1
      setSelectionTrail(t1)
    }

    selectedPathRef.current = prev
    setSelectedPath(prev)
    resetForSelectionChange()
  }, [resetForSelectionChange])

  const goForward = useCallback(() => {
    const f = forwardStackRef.current || []
    if (f.length === 0) return
    const current = selectedPathRef.current
    const next = f[0]

    const nextFwd = f.slice(1)
    forwardStackRef.current = nextFwd
    setForwardStack(nextFwd)

    if (current) {
      const nextBack = [...(backStackRef.current || []), current].slice(-200)
      backStackRef.current = nextBack
      setBackStack(nextBack)
    }

    // trail
    if (next) {
      const t0 = selectionTrailRef.current || []
      const filtered = t0.filter((p) => p !== next)
      const t1 = [...filtered, next].slice(-3)
      selectionTrailRef.current = t1
      setSelectionTrail(t1)
    }

    selectedPathRef.current = next
    setSelectedPath(next)
    resetForSelectionChange()
  }, [resetForSelectionChange])

  const onGraphBackgroundTap = useCallback(() => {
    if (selectedPath) onClearSelection()
  }, [onClearSelection, selectedPath])


  return {
    onClearSelection,
    isSelectedPinned,
    togglePinPath,
    togglePinSelected,
    unpinPath,
    clearPins,
    canGoBack,
    canGoForward,
    goBack,
    goForward,
    onGraphBackgroundTap,
  }
}
