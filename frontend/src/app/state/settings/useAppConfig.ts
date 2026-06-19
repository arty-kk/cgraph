import { useEffect, useState } from 'react'
import type { DepMode } from '@/api'
import { safeStorageGet, safeStorageSet } from '@/shared/lib/storage'
import type { AutoOrMode, RetrievalMode } from '../internal'

/**
 * Owns the persisted "context" configuration shared by the task runner and
 * node-info retrieval: analysis mode/depth/dep-mode, retrieval mode, and the
 * agentic/pack budget settings. Extracted verbatim from useStubGraphApp.
 */
export function useAppConfig() {
  const [mode, setMode] = useState<AutoOrMode>('auto')
  const [depth, setDepth] = useState<number>(1)
  const [depMode, setDepMode] = useState<DepMode>('contracts')
  const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>(() => {
    const v = (safeStorageGet('cs.ui.retrievalMode', '') || '').trim()
    return v === 'pack' ? 'pack' : 'agentic'
  })
  useEffect(() => {
    safeStorageSet('cs.ui.retrievalMode', retrievalMode)
  }, [retrievalMode])

  // Advanced context settings (persisted)
  const [agenticMaxCalls, setAgenticMaxCalls] = useState<number>(() => Number(safeStorageGet('cs.ui.agentic.maxCalls', '24')) || 24)
  const [agenticMaxFileChars, setAgenticMaxFileChars] = useState<number>(() => Number(safeStorageGet('cs.ui.agentic.maxFileChars', '200000')) || 200000)
  const [agenticMaxTotalToolOutputChars, setAgenticMaxTotalToolOutputChars] = useState<number>(() => Number(safeStorageGet('cs.ui.agentic.maxToolChars', '2000000')) || 2000000)
  const [agenticTemperature, setAgenticTemperature] = useState<number>(() => Number(safeStorageGet('cs.ui.agentic.temperature', '0')) || 0)
  const [agenticEvidenceMode, setAgenticEvidenceMode] = useState<boolean>(() => (safeStorageGet('cs.ui.agentic.evidenceMode', '0') || '0') === '1')
  const [packMaxFiles, setPackMaxFiles] = useState<number>(() => Number(safeStorageGet('cs.ui.pack.maxFiles', '25')) || 25)
  const [packMaxCharsPerFile, setPackMaxCharsPerFile] = useState<number>(() => Number(safeStorageGet('cs.ui.pack.maxCharsPerFile', '200000')) || 200000)
  const [packMaxTotalChars, setPackMaxTotalChars] = useState<number>(() => Number(safeStorageGet('cs.ui.pack.maxTotalChars', '2000000')) || 2000000)
  useEffect(() => { safeStorageSet('cs.ui.agentic.maxCalls', String(agenticMaxCalls)) }, [agenticMaxCalls])
  useEffect(() => { safeStorageSet('cs.ui.agentic.maxFileChars', String(agenticMaxFileChars)) }, [agenticMaxFileChars])
  useEffect(() => { safeStorageSet('cs.ui.agentic.maxToolChars', String(agenticMaxTotalToolOutputChars)) }, [agenticMaxTotalToolOutputChars])
  useEffect(() => { safeStorageSet('cs.ui.agentic.temperature', String(agenticTemperature)) }, [agenticTemperature])
  useEffect(() => { safeStorageSet('cs.ui.agentic.evidenceMode', agenticEvidenceMode ? '1' : '0') }, [agenticEvidenceMode])
  useEffect(() => { safeStorageSet('cs.ui.pack.maxFiles', String(packMaxFiles)) }, [packMaxFiles])
  useEffect(() => { safeStorageSet('cs.ui.pack.maxCharsPerFile', String(packMaxCharsPerFile)) }, [packMaxCharsPerFile])
  useEffect(() => { safeStorageSet('cs.ui.pack.maxTotalChars', String(packMaxTotalChars)) }, [packMaxTotalChars])

  return {
    mode, setMode, depth, setDepth, depMode, setDepMode, retrievalMode, setRetrievalMode,
    agenticMaxCalls, setAgenticMaxCalls, agenticMaxFileChars, setAgenticMaxFileChars,
    agenticMaxTotalToolOutputChars, setAgenticMaxTotalToolOutputChars,
    agenticTemperature, setAgenticTemperature, agenticEvidenceMode, setAgenticEvidenceMode,
    packMaxFiles, setPackMaxFiles, packMaxCharsPerFile, setPackMaxCharsPerFile,
    packMaxTotalChars, setPackMaxTotalChars,
  }
}
