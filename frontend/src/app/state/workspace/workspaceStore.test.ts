import { describe, it, expect } from 'vitest'
import {
  workspaceReducer,
  initialWorkspaceState,
  makeWorkspaceSetters,
  type WorkspaceAction,
  type WorkspaceState,
} from './workspaceStore'

function createStore() {
  let state: WorkspaceState = initialWorkspaceState
  const dispatch = (action: WorkspaceAction) => {
    state = workspaceReducer(state, action)
  }
  const setters = makeWorkspaceSetters(dispatch)
  return { get: () => state, setters }
}

describe('workspaceReducer', () => {
  it('applies the updater carried by a set action', () => {
    const next = workspaceReducer(initialWorkspaceState, {
      type: 'set',
      updater: (s) => ({ ...s, selectedPath: 'a/b.ts' }),
    })
    expect(next.selectedPath).toBe('a/b.ts')
  })

  it('returns the same state reference for an unknown action', () => {
    const next = workspaceReducer(initialWorkspaceState, { type: 'noop' } as unknown as WorkspaceAction)
    expect(next).toBe(initialWorkspaceState)
  })
})

describe('makeWorkspaceSetters', () => {
  it('sets a field from a plain value', () => {
    const store = createStore()
    store.setters.setSelectedPath('a/b.ts')
    expect(store.get().selectedPath).toBe('a/b.ts')
  })

  it('supports functional updates (like useState setters)', () => {
    const store = createStore()
    store.setters.setOpenFilePaths(['x'])
    store.setters.setOpenFilePaths((prev) => [...prev, 'y'])
    expect(store.get().openFilePaths).toEqual(['x', 'y'])

    store.setters.setBusyCount((c) => c + 1)
    store.setters.setBusyCount((c) => c + 1)
    expect(store.get().busyCount).toBe(2)
  })

  it('does not touch sibling fields or mutate the initial state', () => {
    const store = createStore()
    store.setters.setSelectedPath('a/b.ts')
    expect(store.get().openFilePaths).toEqual([])
    expect(store.get().activeProject).toBeNull()
    // initial state object is never mutated
    expect(initialWorkspaceState.selectedPath).toBeNull()
  })
})
