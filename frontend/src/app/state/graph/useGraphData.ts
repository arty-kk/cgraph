import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import type { MutableRefObject } from 'react'
import {
  listProjects,
  listRuns,
  getGraph,
  getLocalGraph,
  getNode,
  getContract,
  type GraphData,
  type NodeContract,
  type NodeInfo,
  type Project,
  type RunRecord,
} from '@/api'
import { extractError } from '@/shared/lib/errors'
import { useNotifications } from '../session'
import { useWorkspace } from '../workspace'

type Params = {
  nodeSeqRef: MutableRefObject<number>
}

/**
 * React-Query data layer: projects, runs, graph (mode-aware) and node
 * info/contract, plus the effects syncing query errors and node data into
 * parent state. Extracted verbatim from useStubGraphApp.
 */
export function useGraphData({ nodeSeqRef }: Params) {
  const { setErrorMessage } = useNotifications()
  const ws = useWorkspace()
  const {
    selectedOrgId, activeProject, selectedPath, graphMode, graphHops, graphLimitN, graphLocalMax,
  } = ws.state
  const { setNodeInfo, setContract } = ws.setters
  const projectsQuery = useQuery<Project[]>({
    queryKey: ['projects', selectedOrgId],
    enabled: selectedOrgId !== null,
    queryFn: listProjects,
    initialData: [],
  })

  const runsQuery = useQuery<RunRecord[]>({
    queryKey: ['runs', selectedOrgId, activeProject?.id],
    enabled: selectedOrgId !== null && !!activeProject,
    queryFn: async () => {
      if (!activeProject) return [] as RunRecord[]
      return listRuns(activeProject.id)
    },
    initialData: [],
  })

  const graphQueryKey = useMemo(
    () => {
      const pid = activeProject?.id ?? null
      if (!pid) return ['graph', selectedOrgId, null]
      if (graphMode === 'local') return ['graph', selectedOrgId, pid, 'local', selectedPath ?? null, graphHops, graphLocalMax]
      if (graphMode === 'limit') return ['graph', selectedOrgId, pid, 'limit', graphLimitN]
      if (graphMode === 'full') return ['graph', selectedOrgId, pid, 'full']
      return ['graph', selectedOrgId, pid, graphMode]
    },
    [activeProject?.id, graphMode, graphHops, graphLocalMax, graphLimitN, selectedOrgId, selectedPath],
  )

  const graphQuery = useQuery<GraphData | null>({
    queryKey: graphQueryKey,
    enabled: selectedOrgId !== null && !!activeProject && (graphMode !== 'local' || !!selectedPath),
    queryFn: async (): Promise<GraphData | null> => {
      if (!activeProject) return null
      const projectId = activeProject.id
      if (graphMode === 'local') {
        if (!selectedPath) throw new Error('Select a file to build a local graph.')
        return getLocalGraph(projectId, selectedPath, graphHops, graphLocalMax, graphLocalMax * 2)
      }
      if (graphMode === 'full') return getGraph(projectId, 0)
      if (graphMode === 'limit') return getGraph(projectId, graphLimitN)
      return getGraph(projectId, undefined)
    },
    staleTime: 15_000,
  })

  const nodeQuery = useQuery<{ info: NodeInfo | null; contract: NodeContract | null }>({
    queryKey: ['node', selectedOrgId, activeProject?.id, selectedPath],
    enabled: selectedOrgId !== null && !!activeProject && !!selectedPath,
    queryFn: async () => {
      if (!activeProject || !selectedPath) return { info: null, contract: null }
      const seq = ++nodeSeqRef.current
      const [niRes, ctRes] = await Promise.allSettled([
        getNode(activeProject.id, selectedPath),
        getContract(activeProject.id, selectedPath),
      ])

      if (nodeSeqRef.current !== seq) return { info: null, contract: null }

      let err: string | null = null
      const info = niRes.status === 'fulfilled' ? niRes.value : null
      if (niRes.status !== 'fulfilled') err = extractError(niRes.reason)

      const contractRes = ctRes.status === 'fulfilled' ? ctRes.value : null
      if (ctRes.status !== 'fulfilled') {
        const e2 = extractError(ctRes.reason)
        const shouldIgnoreContractError = Boolean(info?.indexing_started && info?.node_available === false)
        if (!shouldIgnoreContractError) {
          err = err ? `${err}\n${e2}` : e2
        }
      }

      if (info?.indexing_started && info?.node_available === false) {
        setErrorMessage(info.message || 'Индексация запущена, узел временно недоступен')
      } else if (err) {
        setErrorMessage(err)
      }
      return { info, contract: contractRes }
    },
  })

  useEffect(() => {
    const queryError =
      (projectsQuery.error as Error | null) ||
      (graphQuery.error as Error | null) ||
      (nodeQuery.error as Error | null) ||
      (runsQuery.error as Error | null)

    if (queryError) setErrorMessage(extractError(queryError))
  }, [graphQuery.error, nodeQuery.error, projectsQuery.error, runsQuery.error])

  useEffect(() => {
    if (nodeQuery.data) {
      setNodeInfo(nodeQuery.data.info)
      setContract(nodeQuery.data.contract)
    }
  }, [nodeQuery.data])

  return { projectsQuery, runsQuery, graphQuery, nodeQuery, graphQueryKey }
}
