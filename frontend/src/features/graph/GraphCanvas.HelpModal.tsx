import { Modal } from '@/shared/ui/Modal'
import { EDGE_IN_COLOR, EDGE_OUT_COLOR } from './GraphCanvas.storage'

export function GraphHelpModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
      <Modal open={open} title="How to use this (quick)" onClose={onClose}>
        <div className="space-y-4 text-sm">
          <div className="rounded-md border border-neutral-800 bg-neutral-950/70 p-3">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-neutral-500">Basics</div>
            <div className="mt-2 space-y-2 text-neutral-200">
              <div>
                <span className="font-semibold">1) Scan</span> — index the project (files and dependencies).
              </div>
              <div>
                <span className="font-semibold">2) Pick a file</span> — click a node or press <span className="font-mono">Ctrl/⌘+K</span> and type part of a path.
              </div>
              <div>
                <span className="font-semibold">3) Read the graph</span>: nodes = files, arrows = dependencies (import/use).
                For a selected node, edges are highlighted by direction: <span className="font-mono" style={{ color: EDGE_IN_COLOR }}>IN</span> /
                <span className="font-mono ml-1" style={{ color: EDGE_OUT_COLOR }}>OUT</span>.
              </div>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-md border border-neutral-800 bg-neutral-950/60 p-3">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-neutral-500">Mouse actions</div>
              <ul className="mt-2 space-y-1 text-neutral-200">
                <li><span className="font-semibold">Click</span> — select a node.</li>
                <li><span className="font-semibold">Double-click</span> — open the file in the editor.</li>
                <li><span className="font-semibold">Right-click</span> — open the node menu (Center/Pin/Open in editor).</li>
                <li><span className="font-semibold">Background click</span> — clear selection.</li>
              </ul>
            </div>
            <div className="rounded-md border border-neutral-800 bg-neutral-950/60 p-3">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-neutral-500">Shortcuts</div>
              <ul className="mt-2 space-y-1 text-neutral-200">
                <li><span className="font-mono">Ctrl/⌘+K</span> — open search, <span className="font-mono">Enter</span> — open selected file.</li>
                <li><span className="font-mono">↑/↓</span> — move to inbound/outbound neighbor (fallback to next node).</li>
                <li><span className="font-mono">Alt+←/→</span> — back/forward selection history.</li>
                <li><span className="font-mono">Ctrl/⌘+Z</span>/<span className="font-mono">Shift+Z</span> — undo/redo layout edits.</li>
                <li><span className="font-mono">P</span> — pin/unpin selected, <span className="font-mono">H</span> — hide selected.</li>
                <li><span className="font-mono">F</span> — focus mode, <span className="font-mono">Esc</span> — clear/exit focus.</li>
              </ul>
            </div>
          </div>
          <div className="rounded-md border border-neutral-800 bg-neutral-950/70 p-3">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-neutral-500">Workflow</div>
            <div className="mt-2 space-y-2 text-neutral-200">
              <div>
                <span className="font-semibold">Navigation</span>: Trail — recent jumps, Back/Forward — history, Neighbors — incoming/outgoing edges.
              </div>
              <div>
                <span className="font-semibold">Pin</span> — pin up to 3 files to compare metrics.
              </div>
              <div>
                <span className="font-semibold">Tasks</span> — run analyze/evolve/fix for the selected file in the right panel.
              </div>
            </div>
          </div>
        </div>
      </Modal>
  )
}
