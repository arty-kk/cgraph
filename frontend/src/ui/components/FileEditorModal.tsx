// frontend/src/ui/components/FileEditorModal.tsx
import React from 'react'
import { Modal } from './Modal'

type Props = {
  open: boolean
  path: string | null
  content: string
  busy: boolean
  saving: boolean
  dirty: boolean
  truncated: boolean
  error: string | null
  onChange: (value: string) => void
  onReload: () => void | Promise<void>
  onSave: () => void | Promise<void>
  onClose: () => void
}

export function FileEditorModal({
  open,
  path,
  content,
  busy,
  saving,
  dirty,
  truncated,
  error,
  onChange,
  onReload,
  onSave,
  onClose,
}: Props) {
  const title = path ? `File: ${path}` : 'File viewer'

  return (
    <Modal open={open} title={title} onClose={onClose}>
      <div className="flex flex-col gap-3">
        {error && (
          <div className="rounded-md border border-rose-900/60 bg-rose-950/40 px-3 py-2 text-xs text-rose-200">
            {error}
          </div>
        )}
        {truncated && (
          <div className="rounded-md border border-amber-800/70 bg-amber-950/40 px-3 py-2 text-[11px] text-amber-200">
            Файл очень большой — показан только фрагмент. Сохранение заблокировано.
          </div>
        )}
        <textarea
          className="h-[60vh] w-full resize-none rounded-md border border-neutral-800 bg-neutral-950 px-3 py-2 font-mono text-[12px] text-neutral-100 shadow-inner focus:border-indigo-500 focus:outline-none"
          value={content}
          onChange={(e) => onChange(e.target.value)}
          spellCheck={false}
          disabled={busy || saving}
        />
        <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-neutral-400">
          <span>{dirty ? 'Есть несохранённые изменения' : 'Изменений нет'}</span>
          <span>{content.length} chars</span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-3 py-2 text-xs font-semibold disabled:opacity-50"
            onClick={() => void onReload()}
            disabled={busy || saving || !path}
          >
            Reload
          </button>
          <button
            type="button"
            className="rounded-md bg-indigo-600 hover:bg-indigo-500 px-3 py-2 text-xs font-semibold disabled:opacity-50"
            onClick={() => void onSave()}
            disabled={busy || saving || !dirty || truncated || !path}
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button
            type="button"
            className="rounded-md bg-neutral-800 hover:bg-neutral-700 px-3 py-2 text-xs font-semibold disabled:opacity-50"
            onClick={onClose}
            disabled={saving}
          >
            Close
          </button>
        </div>
      </div>
    </Modal>
  )
}
