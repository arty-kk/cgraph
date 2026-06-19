import React, { useMemo } from 'react'
import type { Mode } from '@/api'

type AutoOrMode = 'auto' | Mode

type Props = {
  prompt: string
  setPrompt: (v: string) => void
  promptPlaceholder: string
  busy: boolean
  setMode: (v: AutoOrMode) => void
}

export function NodePanelPromptInput({
  prompt,
  setPrompt,
  promptPlaceholder,
  busy,
  setMode,
}: Props) {
  const promptRef = React.useRef<HTMLTextAreaElement | null>(null)
  const labelRowClass = 'flex items-center gap-2 leading-none'
  const fieldLabelClass = 'text-[11px] font-semibold text-neutral-200'
  const chipBase = 'h-6 px-2 rounded-full border text-[10px] font-semibold transition-colors disabled:opacity-50'
  const chipIdle = 'bg-neutral-900 border-neutral-800 hover:bg-neutral-800'
  const chipActive = 'bg-indigo-950/40 border-indigo-700'
  const promptChips = useMemo(() => {
    return [
      { label: 'Explain', mode: 'analyze' as const, text: 'Explain the file purpose. Point out key functions/classes and responsibilities.' },
      { label: 'Improve', mode: 'evolve' as const, text: 'Suggest improvements and a refactor plan: steps, risks, and how to validate with tests.' },
      { label: 'Fix', mode: 'fix' as const, text: 'Fix the issue: <description>. Preserve behavior/contract. Add/update tests. Return a patch.' },
      { label: 'Impact', mode: 'impact' as const, text: 'If we change <symbol/behavior>, which files are affected? Return a list and brief reasons.' },
    ]
  }, [])

  return (
    <>
      <div className="mt-2">
        <div className={labelRowClass}>
          <span className={fieldLabelClass}>Prompt</span>
        </div>
        <textarea
          ref={promptRef}
          className="mt-1 w-full rounded-md bg-neutral-900 border border-neutral-800 px-3 py-2 text-xs min-h-[110px] placeholder:text-neutral-600 disabled:opacity-50"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          disabled={busy}
          placeholder={promptPlaceholder}
        />
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {promptChips.map((c) => (
          <button
            key={c.label}
            type="button"
            className={[chipBase, prompt.trim() === c.text.trim() ? chipActive : chipIdle].join(' ')}
            onClick={() => {
              setMode(c.mode)
              setPrompt(c.text)
              try {
                window.setTimeout(() => {
                  promptRef.current?.focus?.()
                }, 0)
              } catch {}
            }}
            disabled={busy}
            title="Insert template"
          >
            {c.label}
          </button>
        ))}
      </div>
    </>
  )
}
