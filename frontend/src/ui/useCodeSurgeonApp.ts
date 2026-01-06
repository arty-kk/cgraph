// frontend/src/ui/useCodeSurgeonApp.ts
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  createProject,
  getContract,
  getGraph,
  getNode,
  getRun,
  getRunPatch,
  listProjects,
  listRuns,
  runTask,
  scanProject,
  type DepMode,
  type GraphData,
  type Mode,
  type Project,
  type RunRecord,
  type RunTaskBody,
} from '../api'
import { extractError } from '../lib/errors'

type AutoOrMode = 'auto' | Mode
type GraphMode = 'auto' | 'full' | 'limit'

export function useCodeSurgeonApp() {
  const graphAutoRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [graphBusy, setGraphBusy] = useState(false)
  
  const [projects, setProjects] = useState<Project[]>([])
  const [activeProject, setActiveProject] = useState<Project | null>(null)
  const [graph, setGraph] = useState<GraphData | null>(null)

  const graphSeqRef = useRef(0)
  const nodeSeqRef = useRef(0)
  const nodeBusySeqRef = useRef(0)

  const [newName, setNewName] = useState('my-project')
  const [newPath, setNewPath] = useState('')

  const [graphMode, setGraphMode] = useState<GraphMode>('auto')
  const [graphLimitN, setGraphLimitN] = useState<number>(2000)

  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [nodeInfo, setNodeInfo] = useState<any | null>(null)
  const [contract, setContract] = useState<any | null>(null)

  const [mode, setMode] = useState<AutoOrMode>('auto')
  const [depth, setDepth] = useState<number>(1)
  const [depMode, setDepMode] = useState<DepMode>('contracts')
  const [applyPatch, setApplyPatch] = useState(false)
  const [prompt, setPrompt] = useState('найти точки эволюции бизнеслогики')

  const [runResult, setRunResult] = useState<any | null>(null)
  const [fullPatch, setFullPatch] = useState<string | null>(null)
  const [patchBusy, setPatchBusy] = useState(false)
  const [runLoadBusy, setRunLoadBusy] = useState(false)
  const [runs, setRuns] = useState<RunRecord[]>([])

  const [busy, setBusy] = useState(false)
  const [nodeBusy, setNodeBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  type LoadNodeOpts = {
    preserveError?: boolean
    silent?: boolean
  }

  const loadNodeData = useCallback(async (projectId: number, path: string, opts?: LoadNodeOpts) => {
    const preserveError = !!opts?.preserveError
    const silent = !!opts?.silent
    const seq = ++nodeSeqRef.current

    if (!silent) setSelectedPath(path)
    if (!preserveError) setError(null)
    if (!silent) {
      setNodeInfo(null)
      setContract(null)
    }
    
    if (!silent) {
      nodeBusySeqRef.current = seq
      setNodeBusy(true)
    }

    const [niRes, ctRes] = await Promise.allSettled([getNode(projectId, path), getContract(projectId, path)])

    if (nodeSeqRef.current !== seq) {
      if (!silent && nodeBusySeqRef.current === seq) {
        nodeBusySeqRef.current = 0
        setNodeBusy(false)
      }
      return
    }

    let err: string | null = null

    if (niRes.status === 'fulfilled') setNodeInfo(niRes.value)
    else err = extractError(niRes.reason)

    if (ctRes.status === 'fulfilled') setContract(ctRes.value)
    else err = err ? err + '\n' + extractError(ctRes.reason) : extractError(ctRes.reason)

    if (err) setError(err)
    else if (!preserveError) setError(null)


    if (!silent && nodeBusySeqRef.current === seq) {
      nodeBusySeqRef.current = 0
      setNodeBusy(false)
    }
  }, [])

  useEffect(() => {
    let alive = true
    listProjects()
      .then((xs) => {
        if (!alive) return
        setProjects(xs)
      })
      .catch((e) => {
        if (!alive) return
        setError(extractError(e))
      })
    return () => {
      alive = false
    }
  }, [])

  const selectProjectLocal = useCallback((p: Project) => {
    setActiveProject(p)
    setError(null)

    nodeSeqRef.current++
    nodeBusySeqRef.current = 0
    setNodeBusy(false)

    setGraph(null)
    setRuns([])
    setSelectedPath(null)
    setNodeInfo(null)
    setContract(null)
    setRunResult(null)
    setFullPatch(null)
  }, [])

  const refreshGraph = useCallback(
    async (projectId: number, overrideLimitNodes?: number | null) => {
      const seq = ++graphSeqRef.current
      setGraphBusy(true)

      let limitNodes: number | null | undefined = undefined
      if (typeof overrideLimitNodes === 'number' && Number.isFinite(overrideLimitNodes)) {
        limitNodes = overrideLimitNodes
      } else if (graphMode === 'full') {
        limitNodes = 0
      } else if (graphMode === 'limit') {
        limitNodes = graphLimitN
      } else {
        limitNodes = undefined
      }

      try {
        const [gRes, rrRes] = await Promise.allSettled([getGraph(projectId, limitNodes), listRuns(projectId)])
        if (graphSeqRef.current !== seq) return

        let err: string | null = null
        let nextGraph: GraphData | null = null

        if (gRes.status === 'fulfilled') {
          nextGraph = gRes.value
          setGraph(nextGraph)
        } else {
          err = extractError(gRes.reason)
        }

        if (rrRes.status === 'fulfilled') {
          setRuns(rrRes.value)
        } else {
          const e2 = extractError(rrRes.reason)
          err = err ? err + '\n' + e2 : e2
        }

        if (err) setError(err)
        else setError(null)

        if (nextGraph && selectedPath) {
          const exists = nextGraph.nodes?.some((n) => n.path === selectedPath || n.id === selectedPath)
          if (exists) {
            void loadNodeData(projectId, selectedPath, { preserveError: true, silent: true })
          } else {
            const meta: any = (nextGraph as any)?.meta
            const graphIsLimited = !!meta && ((Number(meta?.limit_nodes) || 0) > 0 || !!meta?.truncated)
            if (!graphIsLimited) {
              nodeSeqRef.current++
              nodeBusySeqRef.current = 0
              setNodeBusy(false)
              setNodeInfo(null)
              setContract(null)
            }
          }
        }
      } finally {
        if (graphSeqRef.current === seq) setGraphBusy(false)
      }
    },
    [graphMode, graphLimitN, loadNodeData, selectedPath]
  )

  useEffect(() => {
    const pid = activeProject?.id
    if (!pid) return

    if (busy || graphBusy) return

    if (graphAutoRefreshTimerRef.current) {
      clearTimeout(graphAutoRefreshTimerRef.current)
      graphAutoRefreshTimerRef.current = null
    }

    graphAutoRefreshTimerRef.current = setTimeout(() => {
      void refreshGraph(pid)
    }, 250)

    return () => {
      if (graphAutoRefreshTimerRef.current) {
        clearTimeout(graphAutoRefreshTimerRef.current)
        graphAutoRefreshTimerRef.current = null
      }
    }
  }, [activeProject?.id, graphMode, graphLimitN, busy, graphBusy, refreshGraph])

  const runOp = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (e: any) {
      setError(extractError(e))
    } finally {
      setBusy(false)
    }
  }, [])

  const onPickProject = useCallback(
    async (p: Project) => {
      selectProjectLocal(p)
      await runOp(async () => refreshGraph(p.id))
    },
    [refreshGraph, runOp, selectProjectLocal]
  )

  const onCreateProject = useCallback(async () => {
    await runOp(async () => {
      const name = newName.trim()
      const root = newPath.trim()
      const p = await createProject(name, root)
      setProjects(await listProjects())
      selectProjectLocal(p)
      await refreshGraph(p.id)
    })
  }, [newName, newPath, refreshGraph, runOp, selectProjectLocal])

  const onScan = useCallback(async () => {
    if (!activeProject) return
    await runOp(async () => {
      await scanProject(activeProject.id)
      await refreshGraph(activeProject.id)
    })
  }, [activeProject, refreshGraph, runOp])

  const onRefresh = useCallback(async () => {
    if (!activeProject) return
    await runOp(async () => refreshGraph(activeProject.id))
  }, [activeProject, refreshGraph, runOp])

  const onLoadFullGraph = useCallback(async () => {
    if (!activeProject) return
    setGraphMode('full')
    await runOp(async () => refreshGraph(activeProject.id, 0))
  }, [activeProject, refreshGraph, runOp])

  const onClearSelection = useCallback(() => {
    nodeSeqRef.current++
    nodeBusySeqRef.current = 0
    setNodeBusy(false)
    setSelectedPath(null)
    setNodeInfo(null)
    setContract(null)
    setRunResult(null)
    setFullPatch(null)
    setError(null)
  }, [])

  const onSelectNodePath = useCallback(
    async (path: string) => {
      if (!activeProject) return

      setRunResult(null)
      setFullPatch(null)

      await loadNodeData(activeProject.id, path)
    },
    [activeProject, loadNodeData]
  )

  const onLoadFullPatch = useCallback(async () => {
    if (!activeProject) return
    const runId = Number(runResult?.run_id)
    if (!Number.isFinite(runId) || runId <= 0) return

    setPatchBusy(true)
    setError(null)
    try {
      const r = await getRunPatch(activeProject.id, runId)
      const txt = typeof r?.patch_unified_diff === 'string' ? r.patch_unified_diff : ''
      setFullPatch(txt)
    } catch (e: any) {
      setError(extractError(e))
    } finally {
      setPatchBusy(false)
    }
  }, [activeProject, runResult])

  const onLoadRun = useCallback(
    async (runId: number) => {
      if (!activeProject) return
      if (!Number.isFinite(runId) || runId <= 0) return

      setRunLoadBusy(true)
      setError(null)
      try {
        const r = await getRun(activeProject.id, runId)
        setRunResult({
          run_id: r.id,
          mode: r.mode,
          depth: undefined,
          dep_mode: undefined,
          result: r.result,
          applied: null,
        })
        setFullPatch(null)

        if (typeof r.target_path === 'string' && r.target_path) {
          await loadNodeData(activeProject.id, r.target_path)
        }
      } catch (e: any) {
        setError(extractError(e))
      } finally {
        setRunLoadBusy(false)
      }
    },
    [activeProject, loadNodeData]
  )

  const onRun = useCallback(async () => {
    if (!activeProject || !selectedPath) return

    await runOp(async () => {
      setRunResult(null)
      setFullPatch(null)

      const body: RunTaskBody = { target_path: selectedPath, prompt, apply_patch: applyPatch }
      if (mode !== 'auto') {
        body.mode = mode
        body.depth = depth
        body.dep_mode = depMode
      }

      const res = await runTask(activeProject.id, body)
      setRunResult(res)

      await refreshGraph(activeProject.id)
    })
  }, [activeProject, selectedPath, runOp, prompt, applyPatch, mode, depth, depMode, refreshGraph])

  const selectedInGraph = useMemo(() => {
    if (!selectedPath || !graph?.nodes?.length) return false
    return graph.nodes.some((n) => n.path === selectedPath || n.id === selectedPath)
  }, [graph, selectedPath])

  const canRun = useMemo(() => {
    const fileReady = !!selectedPath && (contract != null || nodeInfo != null)
    return (
      !!activeProject &&
      !!selectedPath &&
      fileReady &&
      selectedInGraph &&
      !!prompt.trim() &&
      !busy &&
      !nodeBusy
    )
  }, [activeProject, selectedPath, contract, nodeInfo, selectedInGraph, prompt, busy, nodeBusy])

  return {
    // state
    projects,
    activeProject,
    graph,
    runs,
    newName,
    newPath,
    selectedPath,
    selectedInGraph,
    nodeInfo,
    contract,
    mode,
    depth,
    depMode,
    applyPatch,
    prompt,
    runResult,
    fullPatch,
    busy,
    graphBusy,
    nodeBusy,
    patchBusy,
    runLoadBusy,
    error,
    graphMode,
    graphLimitN,

    // setters (UI)
    setNewName,
    setNewPath,
    setGraphMode,
    setGraphLimitN,
    setMode,
    setDepth,
    setDepMode,
    setApplyPatch,
    setPrompt,

    // actions
    onPickProject,
    onCreateProject,
    onScan,
    onRefresh,
    onLoadFullGraph,
    onClearSelection,
    onSelectNodePath,
    onRun,
    onLoadFullPatch,
    onLoadRun,

    // derived
    canRun,
  }
}
