import React from 'react'

export type HelpTopic = 'projects' | 'graph' | 'search'

function HelpButton({ topic, label, onOpenHelp }: { topic: HelpTopic; label?: string; onOpenHelp: (t: HelpTopic) => void }) {
  return (
    <button
      type="button"
      className="w-3.5 h-3.5 rounded-full border border-neutral-800 bg-neutral-900 text-neutral-200 text-[10px] leading-none font-semibold hover:bg-neutral-800 shrink-0"
      onMouseDown={(e) => {
        e.preventDefault()
        e.stopPropagation()
      }}
      onClick={() => onOpenHelp(topic)}
      aria-label={label || 'Open help'}
      title={label || 'Help'}
    >
      ?
    </button>
  )
}

export function SectionHeader({
  title,
  topic,
  right,
  onOpenHelp,
}: {
  title: string
  topic?: HelpTopic
  right?: React.ReactNode
  onOpenHelp: (t: HelpTopic) => void
}) {
  return (
    <div className="flex items-center justify-between gap-3 min-h-6">
      <div className="flex items-center gap-2">
        <div className="text-sm font-semibold text-neutral-200 leading-none">{title}</div>
        {topic ? <HelpButton topic={topic} label={`Help: ${title}`} onOpenHelp={onOpenHelp} /> : null}
      </div>
      {right ?? null}
    </div>
  )
}
