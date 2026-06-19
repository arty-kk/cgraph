import { useCallback, useEffect, useState } from 'react'
import { safeStorageGet, safeStorageSet } from '@/shared/lib/storage'

/** Persisted UI layout prefs: compact mode + left/right panel open state. Extracted verbatim. */
export function useUiPrefs() {
  const [compactMode, setCompactMode] = useState<boolean>(() => (safeStorageGet('cs.ui.compactMode', '0') || '0') === '1')
  useEffect(() => {
    safeStorageSet('cs.ui.compactMode', compactMode ? '1' : '0')
  }, [compactMode])
  const toggleCompactMode = useCallback(() => setCompactMode((v) => !v), [])

  const [leftPanelOpen, setLeftPanelOpen] = useState<boolean>(() => (safeStorageGet('cs.ui.leftPanelOpen', '1') || '1') !== '0')
  const [rightPanelOpen, setRightPanelOpen] = useState<boolean>(() => (safeStorageGet('cs.ui.rightPanelOpen', '1') || '1') !== '0')
  useEffect(() => { safeStorageSet('cs.ui.leftPanelOpen', leftPanelOpen ? '1' : '0') }, [leftPanelOpen])
  useEffect(() => { safeStorageSet('cs.ui.rightPanelOpen', rightPanelOpen ? '1' : '0') }, [rightPanelOpen])

  const toggleLeftPanel = useCallback(() => setLeftPanelOpen((v) => !v), [])
  const toggleRightPanel = useCallback(() => setRightPanelOpen((v) => !v), [])

  return {
    compactMode, setCompactMode, toggleCompactMode,
    leftPanelOpen, setLeftPanelOpen, toggleLeftPanel,
    rightPanelOpen, setRightPanelOpen, toggleRightPanel,
  }
}
