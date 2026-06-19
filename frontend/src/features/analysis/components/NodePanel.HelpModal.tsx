import { Modal } from '@/shared/ui/Modal'

export type NodePanelHelpTopic = 'details' | 'contract' | 'run' | 'runs' | 'ctxSettings'

export function NodePanelHelpModal({
  helpOpen,
  onClose,
}: {
  helpOpen: NodePanelHelpTopic | null
  onClose: () => void
}) {
  return (
        <Modal
          open={helpOpen != null}
          title={
            helpOpen === 'details'
              ? 'Help: Details'
            :
             helpOpen === 'contract'
              ? 'Help: Contract'
            : helpOpen === 'run'
              ? 'Help: Run task'
            : helpOpen === 'runs'
               ? 'Help: Results'
            : helpOpen === 'ctxSettings'
              ? 'Help: Advanced settings'
            : 'Help'
          }
          onClose={onClose}
        >
          {helpOpen === 'details' && (
            <div className="space-y-2">
              <div className="text-neutral-200 font-semibold">Node metrics</div>
              <div>• <span className="font-mono">LOC</span> — lines of code (as counted by the backend).</div>
              <div>• <span className="font-mono">Fan In / Fan Out</span> — inbound/outbound dependencies in the graph.</div>
              <div>• <span className="font-mono">Complexity</span> — complexity estimate (method depends on the backend).</div>
              <div>• <span className="font-mono">SCC</span> — Strongly Connected Component: id of a cyclic dependency group.</div>
              <div>• <span className="font-mono">Status</span> — label/state from the backend (e.g. <span className="font-mono">new</span>). Exact values depend on the indexer.</div>
            </div>
          )}
          {helpOpen === 'contract' && (
            <div className="space-y-2">
              <div>• Contract — structured description of node API/behavior (what the file/module “promises”).</div>
              <div>• Used for faster/cheaper tasks (especially with dep_mode=contracts).</div>
              <div>• If the contract is empty/stale — run Scan/Refresh.</div>
            </div>
          )}
          {helpOpen === 'run' && (
            <div className="space-y-2">
              <div className="text-neutral-200 font-semibold">Run task: how to choose settings</div>
              <div>• Fill in <span className="font-mono">Prompt</span> and pick a preset if needed.</div>
              <div>• All advanced context settings are now in <span className="font-mono">Advanced settings</span> (can be collapsed/expanded).</div>
              <div>• By default <span className="font-mono">Apply patch</span> is off — enable it only if you need a diff.</div>
            </div>
          )}
          {helpOpen === 'runs' && (
            <div className="space-y-2">
              <div>• Results — history of completed tasks for the project/files.</div>
              <div>• New runs are highlighted until you open the result.</div>
              <div>• The <span className="font-mono">Open</span> button opens a modal with context and a patch.</div>
            </div>
          )}
          {helpOpen === 'ctxSettings' && (
            <div className="space-y-2">
              <div className="text-neutral-200 font-semibold">Advanced settings</div>
              <div>• <span className="font-mono">Context</span>: Agentic — context via tools; Pack — bundled package via graph/contracts.</div>
              <div>• <span className="font-mono">Mode</span>: auto/analyze/evolve/fix/impact — response logic.</div>
              <div>• <span className="font-mono">Depth</span> and <span className="font-mono">Dependencies</span> control depth and dependency types.</div>
              <div>• <span className="font-mono">Apply patch</span> applies a unified diff (usually only for fix).</div>
              <div className="pt-2 text-neutral-200 font-semibold">Limits</div>
              <div>• These control context budget and action count.</div>
            </div>
          )}
        </Modal>
  )
}
