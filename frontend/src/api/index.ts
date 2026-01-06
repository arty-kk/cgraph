// frontend/src/api/index.ts
export { api } from './client'

export type { Project, GraphData, Mode, DepMode, RunTaskBody, RunRecord } from './types'

export { listProjects, createProject, scanProject } from './projects'
export { getGraph } from './graph'
export { getNode, getContract } from './nodes'
export { runTask, listRuns, getRun, getRunPatch } from './tasks'
