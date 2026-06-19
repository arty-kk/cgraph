import React from 'react'

export type HelpTopic = 'details' | 'contract' | 'run' | 'runs' | 'ctxSettings'

function HelpButton({
  topic,
  label,
  onOpenHelp,
}: {
  topic: HelpTopic
  label?: string
  onOpenHelp: (topic: HelpTopic) => void
}) {
  return (
    <button
      type="button"
      className="w-3.5 h-3.5 rounded-full border border-neutral-800 bg-neutral-900 text-neutral-200 text-[10px] leading-none font-semibold hover:bg-neutral-800 shrink-0"
      onMouseDown={(e) => { e.preventDefault(); e.stopPropagation() }}
      onClick={() => onOpenHelp(topic)}
      aria-label={label || 'Open help'}
      title={label || 'Help'}
    >
      ?
    </button>
  )
}

export function ToggleBtn({
  open,
  onClick,
  title,
}: {
  open: boolean
  onClick: () => void
  title: string
}) {
  return (
    <button
      type="button"
      className="h-6 rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2.5 text-[11px] font-semibold"
      onClick={onClick}
      title={title}
    >
      {open ? 'Hide' : 'Show'}
    </button>
  )
}

export function SectionHeader({
  title,
  topic,
  open,
  onToggle,
  toggleTitle,
  actions,
  onOpenHelp,
}: {
  title: string
  topic: HelpTopic
  open?: boolean
  onToggle?: () => void
  toggleTitle?: string
  actions?: React.ReactNode
  onOpenHelp: (topic: HelpTopic) => void
}) {
  return (
    <div className="flex items-center justify-between gap-3 min-h-6">
      <div className="flex items-center gap-2">
        <div className="text-sm font-semibold text-neutral-200 leading-none">{title}</div>
        <HelpButton topic={topic} label={`Help: ${title}`} onOpenHelp={onOpenHelp} />
      </div>
      <div className="flex items-center gap-2">
        {actions}
        {typeof open === 'boolean' && onToggle ? (
          <ToggleBtn open={open} onClick={onToggle} title={toggleTitle || `${open ? 'Hide' : 'Show'} ${title}`} />
        ) : null}
      </div>
    </div>
  )
}
