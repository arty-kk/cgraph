import { useCallback } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import type { QueryClient } from '@tanstack/react-query'
import {
  deleteRun,
  getRun,
  getRunPatch,
  applyRunPatch,
  runTask,
  isTaskStatus,
  waitForTaskResult,
  type RunTaskBody,
  type RunTaskResult,
  type Project,
  type GraphData,
  type NodeInfo,
  type NodeContract,
  type TaskStatus,
} from '@/api'
import { extractError } from '@/shared/lib/errors'
import { clampInt } from '@/shared/lib/number'
import { getRunGraphStaleState, type GraphMode } from '../internal'
import type { useAppConfig } from '../settings/useAppConfig'

type Params = {
  config: ReturnType<typeof useAppConfig>
  activeProject: Project | null
  applyPatch: boolean
  contract: NodeContract | null
  graph: GraphData | null
  graphMode: GraphMode
  nodeInfo: NodeInfo | null
  notifyInfo: (message: string) => void
  prompt: string
  queryClient: QueryClient
  runOp: (fn: () => Promise<void>) => Promise<void>
  runResult: RunTaskResult | null
  selectedOrgId: number | null
  selectedPath: string | null
  setErrorMessage: (message: string | null) => void
  setFullPatch: Dispatch<SetStateAction<string | null>>
  setGraphMode: Dispatch<SetStateAction<GraphMode>>
  setGraphStale: Dispatch<SetStateAction<boolean>>
  setGraphStaleMessage: Dispatch<SetStateAction<string | null>>
  setPatchBusy: Dispatch<SetStateAction<boolean>>
  setRightPanelOpen: Dispatch<SetStateAction<boolean>>
  setRunLoadBusy: Dispatch<SetStateAction<boolean>>
  setRunResult: Dispatch<SetStateAction<RunTaskResult | null>>
  setSelection: (nextRaw: string | null, opts?: { pushHistory?: boolean }) => void
  trackTaskStatus: (task: TaskStatus, kind: 'scan' | 'docs' | 'run', label: string) => void
}

/**
 * Run/patch lifecycle + graph-interaction handlers (delete run, load/apply
 * patch, load run, run task, quick summary, expanded-context run, node taps
 * and path navigation). Extracted verbatim from useStubGraphApp.
 */
export function useGraphRunActions({
  config,
  activeProject,
  applyPatch,
  contract,
  graph,
  graphMode,
  nodeInfo,
  notifyInfo,
  prompt,
  queryClient,
  runOp,
  runResult,
  selectedOrgId,
  selectedPath,
  setErrorMessage,
  setFullPatch,
  setGraphMode,
  setGraphStale,
  setGraphStaleMessage,
  setPatchBusy,
  setRightPanelOpen,
  setRunLoadBusy,
  setRunResult,
  setSelection,
  trackTaskStatus,
}: Params) {
  const {
    mode, depth, depMode, retrievalMode,
    agenticMaxCalls, setAgenticMaxCalls,
    agenticMaxFileChars, setAgenticMaxFileChars,
    agenticMaxTotalToolOutputChars, setAgenticMaxTotalToolOutputChars,
    agenticTemperature, agenticEvidenceMode,
    packMaxFiles, setPackMaxFiles,
    packMaxCharsPerFile, setPackMaxCharsPerFile,
    packMaxTotalChars, setPackMaxTotalChars,
  } = config

  const onDeleteRun = useCallback(
    async (runId: number) => {
      const pid = Number(activeProject?.id)
      if (!Number.isFinite(pid) || pid <= 0 || !Number.isFinite(runId)) return
      await runOp(async () => {
        await deleteRun(pid, runId)
        if (runResult?.run_id === runId) {
          setRunResult(null)
          setFullPatch(null)
        }
        await queryClient.invalidateQueries({ queryKey: ['runs', selectedOrgId, pid] })
      })
    },
    [activeProject?.id, queryClient, runOp, runResult?.run_id, selectedOrgId]
  )

  const onLoadFullGraph = useCallback(() => {
    if (!activeProject) return
    setGraphMode('full')
    setErrorMessage(null)
  }, [activeProject, setErrorMessage])

  const onNavigatePath = useCallback(
    (path: string) => {
      if (!activeProject) return
      const p = String(path || '').trim()
      if (!p) return
      setSelection(p, { pushHistory: true })
    },
    [activeProject, setSelection],
  )

  const onSelectNodePath = useCallback(
    (path: string) => {
      if (!activeProject) return
      const p = String(path || '').trim()
      if (!p) return
      setSelection(p, { pushHistory: true })
      const hasGraph = Boolean(graph?.nodes && Array.isArray(graph.nodes) && graph.nodes.length > 0)
      const inCurrentGraph = hasGraph ? Boolean(graph?.nodes?.some((n: any) => n?.path === p || n?.id === p)) : true

      if (!inCurrentGraph && graphMode !== 'local') {
        setGraphMode('local')
        notifyInfo('Switched to local graph to reveal selection')
      }
    },
    [activeProject, graph?.nodes, graphMode, notifyInfo, setSelection]
  )

  const onGraphNodeTap = useCallback(
    (path: string) => {
      if (!activeProject) return
      setSelection(path, { pushHistory: true })
    },
    [activeProject, setSelection]
  )

  const onLoadFullPatch = useCallback(async () => {
    if (!activeProject) return
    const runId = Number(runResult?.run_id)
    if (!Number.isFinite(runId) || runId <= 0) return

    setPatchBusy(true)
    setErrorMessage(null)
    try {
      const r = await getRunPatch(activeProject.id, runId)
      const txt = typeof r?.patch_unified_diff === 'string' ? r.patch_unified_diff : ''
      setFullPatch(txt)
    } catch (e: any) {
      setErrorMessage(extractError(e))
    } finally {
      setPatchBusy(false)
    }
  }, [activeProject, runResult])

  const onApplyRunPatch = useCallback(async () => {
    if (!activeProject) return
    const runId = Number(runResult?.run_id)
    if (!Number.isFinite(runId) || runId <= 0) return

    await runOp(async () => {
      const res = await applyRunPatch(activeProject.id, runId)
      setRunResult((prev) => {
        if (!prev || prev.run_id !== runId) return prev
        return {
          ...prev,
          applied: res.applied ?? undefined,
        }
      })
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['graph', selectedOrgId, activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['node', selectedOrgId, activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['files', selectedOrgId, activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['runs', selectedOrgId, activeProject.id] }),
      ])
    })
  }, [activeProject, queryClient, runOp, runResult?.run_id, selectedOrgId])

  const onLoadRun = useCallback(
    async (runId: number) => {
      if (!activeProject) return
      if (!Number.isFinite(runId) || runId <= 0) return

      setRunLoadBusy(true)
      setErrorMessage(null)
      try {
        const r = await getRun(activeProject.id, runId)
        const tp = typeof r.target_path === 'string' ? r.target_path.trim() : ''

        if (tp) setSelection(tp, { pushHistory: true })

        setRunResult({
          run_id: r.id,
          mode: r.mode,
          depth: r.depth ?? undefined,
          dep_mode: r.dep_mode ?? undefined,
          retrieval: r.retrieval ?? undefined,
          retrieval_settings: r.retrieval_settings ?? undefined,
          apply_patch: r.apply_patch ?? undefined,
          result: r.result,
          applied: r.applied ?? undefined,
          warning: r.warning ?? undefined,
        })
        const runGraphState = getRunGraphStaleState(r.warning)
        if (runGraphState.stale) {
          setGraphStale(true)
          setGraphStaleMessage(runGraphState.message)
        }
        setFullPatch(null)
      } catch (e: any) {
        setErrorMessage(extractError(e))
      } finally {
        setRunLoadBusy(false)
      }
    },
    [activeProject, setSelection]
  )

  const buildRunBody = useCallback(
    (extra?: Partial<RunTaskBody>): RunTaskBody | null => {
      if (!selectedPath) return null
      const clampedPackMaxFiles = clampInt(packMaxFiles, 1, 80)
      const clampedPackMaxCharsPerFile = clampInt(packMaxCharsPerFile, 1, 200_000)
      let clampedPackMaxTotalChars = clampInt(packMaxTotalChars, 1, 2_000_000)
      if (clampedPackMaxTotalChars < clampedPackMaxCharsPerFile) {
        clampedPackMaxTotalChars = clampedPackMaxCharsPerFile
      }
      if (clampedPackMaxFiles !== packMaxFiles) setPackMaxFiles(clampedPackMaxFiles)
      if (clampedPackMaxCharsPerFile !== packMaxCharsPerFile) setPackMaxCharsPerFile(clampedPackMaxCharsPerFile)
      if (clampedPackMaxTotalChars !== packMaxTotalChars) setPackMaxTotalChars(clampedPackMaxTotalChars)

      const clampedAgenticMaxCalls = clampInt(agenticMaxCalls, 1, 100)
      const clampedAgenticMaxFileChars = clampInt(agenticMaxFileChars, 1, 200_000)
      const clampedAgenticMaxTotalToolOutputChars = clampInt(agenticMaxTotalToolOutputChars, 1, 2_000_000)
      if (clampedAgenticMaxCalls !== agenticMaxCalls) setAgenticMaxCalls(clampedAgenticMaxCalls)
      if (clampedAgenticMaxFileChars !== agenticMaxFileChars) setAgenticMaxFileChars(clampedAgenticMaxFileChars)
      if (clampedAgenticMaxTotalToolOutputChars !== agenticMaxTotalToolOutputChars) {
        setAgenticMaxTotalToolOutputChars(clampedAgenticMaxTotalToolOutputChars)
      }

      const body: RunTaskBody = {
        target_path: selectedPath,
        prompt,
        apply_patch: applyPatch,
        agentic: retrievalMode === 'agentic',
      }
      if (retrievalMode === 'agentic') {
        body.agentic_max_calls = clampedAgenticMaxCalls
        body.agentic_max_file_chars = clampedAgenticMaxFileChars
        body.agentic_max_total_tool_output_chars = clampedAgenticMaxTotalToolOutputChars
        body.agentic_temperature = agenticTemperature
        body.agentic_evidence_mode = agenticEvidenceMode
      } else {
        body.pack_max_files = clampedPackMaxFiles
        body.pack_max_chars_per_file = clampedPackMaxCharsPerFile
        body.pack_max_total_chars = clampedPackMaxTotalChars
      }
      if (mode !== 'auto') {
        body.mode = mode
        body.depth = depth
        if (retrievalMode === 'pack') body.dep_mode = depMode
      }

      return extra ? { ...body, ...extra } : body
    },
    [
      agenticMaxCalls,
      agenticEvidenceMode,
      agenticMaxFileChars,
      agenticMaxTotalToolOutputChars,
      agenticTemperature,
      applyPatch,
      depth,
      depMode,
      mode,
      packMaxCharsPerFile,
      packMaxFiles,
      packMaxTotalChars,
      prompt,
      retrievalMode,
      selectedPath,
      setAgenticMaxCalls,
      setAgenticMaxFileChars,
      setAgenticMaxTotalToolOutputChars,
      setPackMaxCharsPerFile,
      setPackMaxFiles,
      setPackMaxTotalChars,
    ]
  )

  const runTaskTracked = useCallback(
    async (projectId: number, body: RunTaskBody, label: string) => {
      const initial = await runTask(projectId, body)
      if (isTaskStatus(initial)) {
        trackTaskStatus(initial, 'run', label)
      }
      return waitForTaskResult<RunTaskResult>(initial)
    },
    [trackTaskStatus],
  )

  const onRun = useCallback(async () => {
    if (!activeProject || !selectedPath) return

    await runOp(async () => {
      setRunResult(null)
      setFullPatch(null)

      const body = buildRunBody()
      if (!body) return
      const res = await runTaskTracked(activeProject.id, body, `Run ${selectedPath}`)
      setRunResult(res)

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['graph', selectedOrgId, activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['runs', selectedOrgId, activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['node', selectedOrgId, activeProject.id] }),
      ])
    })
  }, [
    activeProject,
    selectedPath,
    runOp,
    buildRunBody,
    runTaskTracked,
    queryClient,
    selectedOrgId,
  ])

  const onQuickSummary = useCallback(async (path: string) => {
    if (!activeProject) {
      notifyInfo('Select a project first.')
      return
    }
    if (!path) {
      notifyInfo('Select a file first.')
      return
    }
    if (!selectedPath || path !== selectedPath) {
      notifyInfo('Select the file to load its info before summarizing.')
      return
    }
    if (!contract && !nodeInfo) {
      notifyInfo('Loading file info, try again in a moment.')
      return
    }

    await runOp(async () => {
      setRunResult(null)
      setFullPatch(null)
      setRightPanelOpen(true)

      const clampedPackMaxFiles = clampInt(packMaxFiles, 1, 200)
      const clampedPackMaxCharsPerFile = clampInt(packMaxCharsPerFile, 1, 200_000)
      const clampedPackMaxTotalChars = clampInt(packMaxTotalChars, 1, 2_000_000)
      if (clampedPackMaxFiles !== packMaxFiles) setPackMaxFiles(clampedPackMaxFiles)
      if (clampedPackMaxCharsPerFile !== packMaxCharsPerFile) setPackMaxCharsPerFile(clampedPackMaxCharsPerFile)
      if (clampedPackMaxTotalChars !== packMaxTotalChars) setPackMaxTotalChars(clampedPackMaxTotalChars)

      const clampedAgenticMaxCalls = clampInt(agenticMaxCalls, 1, 100)
      const clampedAgenticMaxFileChars = clampInt(agenticMaxFileChars, 1, 200_000)
      const clampedAgenticMaxTotalToolOutputChars = clampInt(agenticMaxTotalToolOutputChars, 1, 2_000_000)
      if (clampedAgenticMaxCalls !== agenticMaxCalls) setAgenticMaxCalls(clampedAgenticMaxCalls)
      if (clampedAgenticMaxFileChars !== agenticMaxFileChars) setAgenticMaxFileChars(clampedAgenticMaxFileChars)
      if (clampedAgenticMaxTotalToolOutputChars !== agenticMaxTotalToolOutputChars) {
        setAgenticMaxTotalToolOutputChars(clampedAgenticMaxTotalToolOutputChars)
      }

      const body: RunTaskBody = {
        target_path: path,
        prompt: '1-абзацное описание: назначение файла, ключевые ответственности/точки входа, важные зависимости; 3–5 предложений, без списков',
        mode: 'analyze',
        dep_mode: 'contracts',
        depth: 1,
        apply_patch: false,
        agentic: retrievalMode === 'agentic',
      }

      if (retrievalMode === 'agentic') {
        body.agentic_max_calls = clampedAgenticMaxCalls
        body.agentic_max_file_chars = clampedAgenticMaxFileChars
        body.agentic_max_total_tool_output_chars = clampedAgenticMaxTotalToolOutputChars
        body.agentic_temperature = agenticTemperature
        body.agentic_evidence_mode = agenticEvidenceMode
      } else {
        body.pack_max_files = clampedPackMaxFiles
        body.pack_max_chars_per_file = clampedPackMaxCharsPerFile
        body.pack_max_total_chars = clampedPackMaxTotalChars
      }

      const res = await runTaskTracked(activeProject.id, body, `Summary ${path}`)
      setRunResult(res)

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['graph', selectedOrgId, activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['runs', selectedOrgId, activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['node', selectedOrgId, activeProject.id] }),
      ])
    })
  }, [
    activeProject,
    agenticEvidenceMode,
    agenticMaxCalls,
    agenticMaxFileChars,
    agenticMaxTotalToolOutputChars,
    agenticTemperature,
    contract,
    nodeInfo,
    notifyInfo,
    packMaxCharsPerFile,
    packMaxFiles,
    packMaxTotalChars,
    queryClient,
    retrievalMode,
    runTaskTracked,
    runOp,
    selectedPath,
    selectedOrgId,
    setAgenticMaxCalls,
    setAgenticMaxFileChars,
    setAgenticMaxTotalToolOutputChars,
    setPackMaxCharsPerFile,
    setPackMaxFiles,
    setPackMaxTotalChars,
    setRightPanelOpen,
  ])

  const onRunWithExpandedContext = useCallback(async (extra?: Partial<RunTaskBody>) => {
    if (!activeProject || !selectedPath) return

    await runOp(async () => {
      setRunResult(null)
      setFullPatch(null)

      const body = buildRunBody({ allow_out_of_context_patch: true, ...extra })
      if (!body) return
      const res = await runTaskTracked(activeProject.id, body, `Run ${selectedPath}`)
      setRunResult(res)

      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['graph', selectedOrgId, activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['runs', selectedOrgId, activeProject.id] }),
        queryClient.invalidateQueries({ queryKey: ['node', selectedOrgId, activeProject.id] }),
      ])
    })
  }, [activeProject, selectedPath, runOp, buildRunBody, queryClient, selectedOrgId, runTaskTracked])

  return {
    onDeleteRun,
    onLoadFullGraph,
    onNavigatePath,
    onSelectNodePath,
    onGraphNodeTap,
    onLoadFullPatch,
    onApplyRunPatch,
    onLoadRun,
    onRun,
    onQuickSummary,
    onRunWithExpandedContext,
  }
}
