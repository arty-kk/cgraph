// frontend/src/api/index.ts
export { api } from './client'

export type {
  Project,
  GraphData,
  GraphMeta,
  GraphNode,
  NodeSearchItem,
  SemanticSearchItem,
  SemanticSearchResult,
  TextSearchMatch,
  TextSearchResult,
  NodeContract,
  NodeInfo,
  FileContent,
  FileSaveResult,
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

export {
  listProjects,
  createProjectFromRoot,
  createProjectFromSnapshot,
  deleteProject,
  scanProject,
  listProjectFiles,
  getProjectDocs,
  buildProjectDocs,
  searchProjectSemantic,
  searchProjectText,
} from './projects'
export { getGraph, getLocalGraph, searchNodes } from './graph'
export { getNode, getContract, getFileContent, updateFileContent, createFile, renameFile, deleteFile } from './nodes'
export {
  runTask,
  listRuns,
  getRun,
  getRunPatch,
  applyRunPatch,
  deleteRun,
  getTaskStatus,
  waitForTaskResult,
} from './tasks'
