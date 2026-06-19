import React from 'react'
import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

import type { RunTaskResult } from '@/api'
import { NodePanelResultModal } from './NodePanelResultModal'

// Representative server payload: includes agentic runtime fields (tool_trace,
// tool_calls_used, ...) that the panel reads dynamically, so it is widened to
// RunTaskResult via unknown.
const sampleRunResult = {
  run_id: 42,
  mode: 'analyze',
  depth: 2,
  dep_mode: 'contracts',
  retrieval: 'agentic',
  retrieval_settings: {
    agentic: {
      tool_calls_used: 3,
      max_calls: 24,
      tool_output_chars_used: 1500,
      max_total_tool_output_chars: 2_000_000,
      max_file_chars: 200_000,
      self_check_missing_context: ['needs auth config'],
      tool_trace: [
        {
          name: 'search_text',
          status: 'ok',
          args: { query: 'login' },
          duration_ms: 1200,
          response_chars: 800,
          cache_hit: true,
        },
      ],
    },
  },
  apply_patch: true,
  result: { summary: 'All good', patch_unified_diff: '--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n' },
  applied: { modified: ['src/main.ts'] },
  warning: 'graph not built',
} as unknown as RunTaskResult

const baseProps = {
  onClose: () => {},
  runResult: sampleRunResult,
  activeRunId: null,
  runLoadBusy: false,
  busy: false,
  activeProject: { id: 1, name: 'demo' },
  canRun: true,
  patchBusy: false,
  fullPatch: null,
  notifyInfo: () => {},
  retrievalMode: 'agentic' as const,
  depth: 2,
  agenticMaxCalls: 24,
  agenticMaxFileChars: 200_000,
  agenticMaxTotalToolOutputChars: 2_000_000,
  packMaxFiles: 25,
  packMaxTotalChars: 2_000_000,
  onLoadRun: () => {},
  onRunWithExpandedContext: () => {},
  onScan: () => {},
  onApplyRunPatch: () => {},
  onLoadFullPatch: () => {},
}

describe('NodePanelResultModal', () => {
  it('renders nothing while closed', () => {
    const html = renderToStaticMarkup(<NodePanelResultModal {...baseProps} open={false} />)
    expect(html).toBe('')
  })

  it('renders the run header, retrieval summary and quality limits when open', () => {
    const html = renderToStaticMarkup(<NodePanelResultModal {...baseProps} open />)
    expect(html).toContain('Result')
    expect(html).toContain('run_id:')
    expect(html).toContain('ctx: agentic')
    expect(html).toContain('Quality / Context')
    // missingContextHints surfaced from self_check_missing_context
    expect(html).toContain('needs auth config')
  })

  it('renders the agentic tool trace with formatted command and metrics', () => {
    const html = renderToStaticMarkup(<NodePanelResultModal {...baseProps} open />)
    expect(html).toContain('Static analysis trace')
    expect(html).toContain('rg -n') // formatTraceCommand(search_text)
    expect(html).toContain('login')
    expect(html).toContain('1.20s') // fmtDuration(1200)
    expect(html).toContain('cache hit')
  })

  it('surfaces the stale-graph warning, applied files and the patch section', () => {
    const html = renderToStaticMarkup(<NodePanelResultModal {...baseProps} open />)
    expect(html).toContain('Scan/Rescan now')
    expect(html).toContain('Patch Applied')
    expect(html).toContain('src/main.ts')
    expect(html).toContain('Patch (Unified Diff)')
    expect(html).toContain('Apply patch now')
  })
})
