import type { NodeContract, NodeInfo, Project, RunTaskResult } from '@/api'
import type {
  DraftEntry,
  FileEditorEntry,
  FileSaveBanner,
  GraphMode,
  PendingFileJump,
  WorkspaceView,
} from '../internal'

/**
 * The full UI state that the StubGraph workspace operates on. Previously this
 * lived as ~47 individual useState hooks inside useStubGraphApp; it is now a
 * single store so the orchestration hooks can read state + mutate through
 * context instead of receiving dozens of setters as parameters.
 */
export type WorkspaceState = {
  selectedOrgId: number | null
  orgSelectionStorageFailureMarker: number
  activeProject: Project | null
  newName: string
  newArchive: File | null
  newPath: string
  graphMode: GraphMode
  graphLimitN: number
  graphHops: number
  graphLocalMax: number
  gotoLineRequestId: number
  findRequestId: number
  replaceRequestId: number
  outlineRequestId: number
  backStack: string[]
  forwardStack: string[]
  selectionTrail: string[]
  pinnedPaths: string[]
  selectedPath: string | null
  paletteOpen: boolean
  nodeInfo: NodeInfo | null
  contract: NodeContract | null
  applyPatch: boolean
  prompt: string
  runResult: RunTaskResult | null
  fullPatch: string | null
  patchBusy: boolean
  runLoadBusy: boolean
  busyCount: number
  focusGraph: boolean
  workspaceView: WorkspaceView
  openFilePaths: string[]
  fileEditorsByPath: Record<string, FileEditorEntry>
  activeFilePath: string | null
  fileSaveBanner: FileSaveBanner | null
  graphStale: boolean
  graphStaleMessage: string | null
  draftsByPath: Record<string, DraftEntry>
  draftRestore: { path: string; draft: DraftEntry } | null
  pendingClosePath: string | null
  pendingClosePaths: string[]
  pendingActivePath: string | null
  pendingReloadPath: string | null
  pendingJump: PendingFileJump | null
  confirmOpen: boolean
  confirmReason: string | null
  pendingView: WorkspaceView | null
}

export const initialWorkspaceState: WorkspaceState = {
  selectedOrgId: null,
  orgSelectionStorageFailureMarker: 0,
  activeProject: null,
  newName: 'my-project',
  newArchive: null,
  newPath: '',
  graphMode: 'limit',
  graphLimitN: 2000,
  graphHops: 2,
  graphLocalMax: 400,
  gotoLineRequestId: 0,
  findRequestId: 0,
  replaceRequestId: 0,
  outlineRequestId: 0,
  backStack: [],
  forwardStack: [],
  selectionTrail: [],
  pinnedPaths: [],
  selectedPath: null,
  paletteOpen: false,
  nodeInfo: null,
  contract: null,
  applyPatch: false,
  prompt: '',
  runResult: null,
  fullPatch: null,
  patchBusy: false,
  runLoadBusy: false,
  busyCount: 0,
  focusGraph: false,
  workspaceView: 'graph',
  openFilePaths: [],
  fileEditorsByPath: {},
  activeFilePath: null,
  fileSaveBanner: null,
  graphStale: false,
  graphStaleMessage: null,
  draftsByPath: {},
  draftRestore: null,
  pendingClosePath: null,
  pendingClosePaths: [],
  pendingActivePath: null,
  pendingReloadPath: null,
  pendingJump: null,
  confirmOpen: false,
  confirmReason: null,
  pendingView: null,
}

/**
 * A single generic action carrying a state updater keeps the reducer trivially
 * correct (it mirrors useState semantics) while still funnelling every change
 * through one dispatch. Named compound actions can be layered on top later.
 */
export type WorkspaceAction = { type: 'set'; updater: (state: WorkspaceState) => WorkspaceState }

export function workspaceReducer(state: WorkspaceState, action: WorkspaceAction): WorkspaceState {
  switch (action.type) {
    case 'set':
      return action.updater(state)
    default:
      return state
  }
}

/** A useState-style setter: accepts a value or an updater function. */
export type Setter<T> = (value: T | ((prev: T) => T)) => void

/** Bound setters named `set<Field>` for every key of WorkspaceState. */
export type WorkspaceSetters = {
  [K in keyof WorkspaceState as `set${Capitalize<string & K>}`]: Setter<WorkspaceState[K]>
}

type Dispatch = (action: WorkspaceAction) => void

/**
 * Build the `set<Field>` setters from a (stable) dispatch. Each setter mirrors
 * the corresponding useState setter exactly, including functional updates.
 */
export function makeWorkspaceSetters(dispatch: Dispatch): WorkspaceSetters {
  const out = {} as Record<string, Setter<unknown>>
  for (const key of Object.keys(initialWorkspaceState) as (keyof WorkspaceState)[]) {
    const name = `set${key.charAt(0).toUpperCase()}${key.slice(1)}`
    out[name] = (value) =>
      dispatch({
        type: 'set',
        updater: (state) => ({
          ...state,
          [key]: typeof value === 'function' ? (value as (prev: unknown) => unknown)(state[key]) : value,
        }),
      })
  }
  return out as WorkspaceSetters
}
