import { useMemo } from 'react'
import type { GraphData, GraphNode, NodeInfo, NodeContract, Project } from '@/api'
import type { DraftEntry, FileEditorEntry } from './useStubGraphApp.internal'

type Params = {
  selectedPath: string | null
  graph: GraphData | null
  activeProject: Project | null
  activeFilePath: string | null
  fileEditorsByPath: Record<string, FileEditorEntry>
  draftsByPath: Record<string, DraftEntry>
  contract: NodeContract | null
  nodeInfo: NodeInfo | null
  prompt: string
  busy: boolean
  graphQuery: { isFetching: boolean }
  nodeQuery: { isFetching: boolean }
  projectsQuery: { isFetching: boolean }
}

/** Derived display state (selection-in-graph, active editor entry, busy flags, file-editor view fields, draft count, canRun). Extracted verbatim. */
export function useDerivedAppState({
  selectedPath, graph, activeProject, activeFilePath, fileEditorsByPath, draftsByPath,
  contract, nodeInfo, prompt, busy, graphQuery, nodeQuery, projectsQuery,
}: Params) {
  const selectedInGraph = useMemo(() => {
    if (!selectedPath || !graph?.nodes?.length) return false
    return graph.nodes.some((n: GraphNode) => n.path === selectedPath || n.id === selectedPath)
  }, [graph, selectedPath])

  const activeFileEntry = useMemo(() => {
    if (!activeFilePath) return null
    return fileEditorsByPath[activeFilePath] ?? null
  }, [activeFilePath, fileEditorsByPath])

  const graphBusy = graphQuery.isFetching
  const nodeBusy = nodeQuery.isFetching
  const mutationBusy = busy || projectsQuery.isFetching
  const fileEditorDirty = activeFileEntry ? activeFileEntry.content !== activeFileEntry.original : false
  const fileEditorPath = activeFilePath
  const fileEditorContent = activeFileEntry?.content ?? ''
  const fileEditorOriginal = activeFileEntry?.original ?? ''
  const fileEditorTruncated = activeFileEntry?.truncated ?? false
  const fileEditorBusy = activeFileEntry?.busy ?? false
  const fileEditorSaving = activeFileEntry?.saving ?? false
  const fileEditorError = activeFileEntry?.error ?? null
  const draftCount = useMemo(() => Object.keys(draftsByPath).length, [draftsByPath])

  const canRun = useMemo(() => {
    const fileReady = !!selectedPath && (contract != null || nodeInfo != null)
    return (
      !!activeProject &&
      !!selectedPath &&
      fileReady &&
      !!prompt.trim() &&
      !mutationBusy &&
      !nodeBusy
    )
  }, [activeProject, selectedPath, contract, nodeInfo, prompt, mutationBusy, nodeBusy])

  return {
    selectedInGraph, activeFileEntry, graphBusy, nodeBusy, mutationBusy,
    fileEditorDirty, fileEditorPath, fileEditorContent, fileEditorOriginal,
    fileEditorTruncated, fileEditorBusy, fileEditorSaving, fileEditorError,
    draftCount, canRun,
  }
}
