// frontend/src/api/index.ts
export { api, setSelectedOrgId, getSelectedOrgId } from './client'

export type {
  Org,
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
  SnapshotCreateTaskResult,
  TaskPollOptions,
  ScanResult,
  ProjectFileItem,
  ProjectFilesResponse,
  ProjectDocs,
  ProjectTreeEntry,
  ProjectTreeResponse,
  FileDependenciesResponse,
  AppConfig,
} from './types'

export {
  listProjects,
  createProjectFromRoot,
  createProjectFromSnapshot,
  deleteProject,
  scanProject,
  scanProjectStatus,
  listProjectFiles,
  listProjectTreeEntries,
  getFileDependencies,
  getProjectDocs,
  buildProjectDocs,
  buildProjectDocsStatus,
  searchProjectSemantic,
  searchProjectText,
} from './projects'
export { getAppConfig } from './config'
export { listOrgs, getOrg, createOrg } from './orgs'
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

export { isTaskStatus, TaskFailureError } from './taskStatus'
