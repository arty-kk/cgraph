import React from 'react'
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import { NodePanel } from './NodePanel'

const makeStorage = (): Storage => ({
  get length() { return 0 },
  clear: () => {},
  getItem: () => null,
  key: () => null,
  removeItem: () => {},
  setItem: () => {},
}) as Storage

describe('NodePanel graph warning copy', () => {
  it('shows explicit Scan/Rescan action without background auto-scan text', () => {
    const originalStorage = globalThis.localStorage
    Object.defineProperty(globalThis, 'localStorage', { value: makeStorage(), configurable: true })

    try {
      const html = renderToStaticMarkup(
        <NodePanel
          activeProject={{ id: 1, name: 'demo' }}
          selectedPath="src/main.ts"
          selectedInGraph
          graphTruncated={false}
          onLoadFullGraph={() => {}}
          onHidePanel={() => {}}
          notifyInfo={() => {}}
          onScan={() => {}}
          nodeBusy={false}
          nodeInfo={null}
          contract={null}
          busy={false}
          mode="auto"
          depth={1}
          depMode="contracts"
          retrievalMode="agentic"
          agenticMaxCalls={24}
          agenticMaxFileChars={200000}
          agenticMaxTotalToolOutputChars={2000000}
          agenticTemperature={0}
          agenticEvidenceMode={false}
          packMaxFiles={25}
          packMaxCharsPerFile={200000}
          packMaxTotalChars={2000000}
          applyPatch={false}
          prompt=""
          setMode={() => {}}
          setDepth={() => {}}
          setDepMode={() => {}}
          setRetrievalMode={() => {}}
          setAgenticMaxCalls={() => {}}
          setAgenticMaxFileChars={() => {}}
          setAgenticMaxTotalToolOutputChars={() => {}}
          setAgenticTemperature={() => {}}
          setAgenticEvidenceMode={() => {}}
          setPackMaxFiles={() => {}}
          setPackMaxCharsPerFile={() => {}}
          setPackMaxTotalChars={() => {}}
          setApplyPatch={() => {}}
          setPrompt={() => {}}
          canRun
          onRun={() => {}}
          onRunWithExpandedContext={() => {}}
          runResult={{ run_id: 11, mode: 'analyze', result: {}, warning: 'graph not built' }}
          fullPatch={null}
          patchBusy={false}
          runLoadBusy={false}
          onLoadFullPatch={() => {}}
          onApplyRunPatch={() => {}}
          onLoadRun={() => {}}
          onDeleteRun={() => {}}
          runs={[]}
        />,
      )

      expect(html).toContain('Scan/Rescan now')
      expect(html).not.toContain('Background Scan started')
    } finally {
      Object.defineProperty(globalThis, 'localStorage', { value: originalStorage, configurable: true })
    }
  })
})
