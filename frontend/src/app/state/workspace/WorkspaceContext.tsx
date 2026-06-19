import React, { createContext, useContext, useMemo, useReducer } from 'react'
import {
  initialWorkspaceState,
  makeWorkspaceSetters,
  workspaceReducer,
  type WorkspaceSetters,
  type WorkspaceState,
} from './workspaceStore'

export type WorkspaceStore = {
  state: WorkspaceState
  setters: WorkspaceSetters
}

const WorkspaceContext = createContext<WorkspaceStore | null>(null)

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(workspaceReducer, initialWorkspaceState)
  // dispatch is stable, so the setters are built once.
  const setters = useMemo(() => makeWorkspaceSetters(dispatch), [dispatch])
  const value = useMemo<WorkspaceStore>(() => ({ state, setters }), [state, setters])
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
}

export function useWorkspace(): WorkspaceStore {
  const ctx = useContext(WorkspaceContext)
  if (!ctx) {
    throw new Error('useWorkspace must be used within a WorkspaceProvider')
  }
  return ctx
}
