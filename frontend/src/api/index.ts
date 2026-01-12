// frontend/src/api/index.ts
export { api } from './client'

export type {
  Project,
  GraphData,
  GraphMeta,
  GraphNode,
  NodeSearchItem,
  NodeContract,
  NodeInfo,
  Mode,
  DepMode,
  RunTaskBody,
  RunRecord,
  RunTaskResult,
  TaskStatus,
  TaskPollOptions,
  ScanResult,
  ProjectFileItem,
  ProjectFilesResponse,
  ProjectDocs,
} from './types'

export { listProjects, createProject, deleteProject, scanProject, listProjectFiles, getProjectDocs, buildProjectDocs } from './projects'
export { getGraph, getLocalGraph, searchNodes } from './graph'
export { getNode, getContract } from './nodes'
export { runTask, listRuns, getRun, getRunPatch, getTaskStatus, waitForTaskResult } from './tasks'
