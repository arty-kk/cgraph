// frontend/src/ui/App.tsx
import React from 'react'
import { ProjectsSidebar } from './components/ProjectsSidebar'
import { GraphCanvas } from './components/GraphCanvas'
import { NodePanel } from './components/NodePanel'
import { useCodeSurgeonApp } from './useCodeSurgeonApp'

export function App() {
  const app = useCodeSurgeonApp()

  return (
    <div className="h-screen w-screen grid grid-cols-[340px_1fr_420px]">
      <ProjectsSidebar
        projects={app.projects}
        activeProject={app.activeProject}
        newName={app.newName}
        newPath={app.newPath}
        busy={app.busy}
        error={app.error}
        onPickProject={app.onPickProject}
        onCreateProject={app.onCreateProject}
        onScan={app.onScan}
        onRefresh={app.onRefresh}
        setNewName={app.setNewName}
        setNewPath={app.setNewPath}
        graphMode={app.graphMode}
        graphLimitN={app.graphLimitN}
        setGraphMode={app.setGraphMode}
        setGraphLimitN={app.setGraphLimitN}
      />

      <GraphCanvas
        graph={app.graph}
        activeProject={app.activeProject}
        busy={app.busy || app.graphBusy}
        selectedPath={app.selectedPath}
        onBackgroundTap={app.onClearSelection}
        onNodeTap={app.onSelectNodePath}
      />

      <NodePanel
        activeProject={app.activeProject}
        selectedPath={app.selectedPath}
        selectedInGraph={app.selectedInGraph}
        graphTruncated={!!(app.graph as any)?.meta?.truncated}
        onLoadFullGraph={app.onLoadFullGraph}
        nodeBusy={app.nodeBusy}
        nodeInfo={app.nodeInfo}
        contract={app.contract}
        busy={app.busy}
        mode={app.mode}
        depth={app.depth}
        depMode={app.depMode}
        applyPatch={app.applyPatch}
        prompt={app.prompt}
        setMode={app.setMode}
        setDepth={app.setDepth}
        setDepMode={app.setDepMode}
        setApplyPatch={app.setApplyPatch}
        setPrompt={app.setPrompt}
        canRun={app.canRun}
        onRun={app.onRun}
        runResult={app.runResult}
        fullPatch={app.fullPatch}
        patchBusy={app.patchBusy}
        runLoadBusy={app.runLoadBusy}
        onLoadFullPatch={app.onLoadFullPatch}
        onLoadRun={app.onLoadRun}
        runs={app.runs}
      />
    </div>
  )
}
