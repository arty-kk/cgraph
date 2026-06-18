// frontend/src/api/index.ts
export { api, setSelectedOrgId, getSelectedOrgId } from '@/shared/api/client'

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
} from '@/shared/types'

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
} from '@/features/projects/api'
export { getAppConfig } from '@/shared/api/config'
export { listOrgs, getOrg, createOrg } from '@/features/orgs/api'
export { getGraph, getLocalGraph, searchNodes } from '@/features/graph/api'
export { getNode, getContract, getFileContent, updateFileContent, createFile, renameFile, deleteFile } from '@/features/files/api'
export {
  runTask,
  listRuns,
  getRun,
  getRunPatch,
  applyRunPatch,
  deleteRun,
  getTaskStatus,
  waitForTaskResult,
} from '@/features/analysis/api'

export { isTaskStatus, TaskFailureError } from '@/features/analysis/taskStatus'
