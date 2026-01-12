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
  const [wrap, setWrap] = React.useState(true)
  const [fontSize, setFontSize] = React.useState(13)
  const [cursorInfo, setCursorInfo] = React.useState({ line: 1, column: 1 })
  const gutterRef = React.useRef<HTMLDivElement | null>(null)
  const textareaRef = React.useRef<HTMLTextAreaElement | null>(null)
  const lineCount = React.useMemo(() => content.split('\n').length || 1, [content])
  const lineNumbers = React.useMemo(() => Array.from({ length: lineCount }, (_, i) => i + 1), [lineCount])

  React.useEffect(() => {
    setCursorInfo({ line: 1, column: 1 })
    if (textareaRef.current) textareaRef.current.scrollTop = 0
    if (gutterRef.current) gutterRef.current.scrollTop = 0
  }, [path, open])

  const updateCursorInfo = React.useCallback(() => {
    const el = textareaRef.current
    if (!el) return
    const idx = el.selectionStart || 0
    const before = content.slice(0, idx)
    const line = before.split('\n').length
    const column = before.length - (before.lastIndexOf('\n') + 1) + 1
    setCursorInfo({ line, column })
  }, [content])

  const handleScroll = (event: React.UIEvent<HTMLTextAreaElement>) => {
    if (!gutterRef.current) return
    gutterRef.current.scrollTop = event.currentTarget.scrollTop
  }

  const handleCopyPath = async () => {
    if (!path) return
    try {
      await navigator.clipboard.writeText(path)
    } catch {}
  }

  const handleSave = () => {
    if (busy || saving || !dirty || truncated || !path) return
    void onSave()
  }

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
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-neutral-800 bg-neutral-950/80 px-3 py-2 text-[11px] text-neutral-300">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full border border-neutral-700 bg-neutral-900/80 px-2 py-0.5 text-[10px] uppercase tracking-[0.2em] text-neutral-400">
              Editor
            </span>
            {path && (
              <span className="max-w-[52vw] truncate text-neutral-100">{path}</span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
              onClick={handleCopyPath}
              disabled={!path}
            >
              Copy path
            </button>
            <button
              type="button"
              className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
              onClick={() => setWrap((prev) => !prev)}
            >
              {wrap ? 'Wrap on' : 'Wrap off'}
            </button>
            <div className="flex items-center gap-2 rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1">
              <span className="text-[10px] uppercase tracking-[0.2em] text-neutral-500">Size</span>
              <input
                type="range"
                min={12}
                max={16}
                step={1}
                value={fontSize}
                onChange={(e) => setFontSize(Number(e.target.value))}
                className="h-1 w-20 accent-indigo-500"
                aria-label="Font size"
              />
              <span className="text-[11px] text-neutral-300">{fontSize}px</span>
            </div>
          </div>
        </div>
        <div className="rounded-lg border border-neutral-800 bg-gradient-to-b from-neutral-950 via-neutral-950 to-neutral-900/70 shadow-inner">
          <div className="flex items-stretch">
            <div
              ref={gutterRef}
              className="hidden max-h-[60vh] min-h-[60vh] w-12 flex-none overflow-hidden border-r border-neutral-800 bg-neutral-950/80 py-3 text-right text-[11px] leading-5 text-neutral-600 sm:block"
            >
              {lineNumbers.map((line) => (
                <div key={line} className="px-2">{line}</div>
              ))}
            </div>
            <textarea
              ref={textareaRef}
              className="min-h-[60vh] w-full resize-none bg-transparent px-4 py-3 font-mono text-neutral-100 focus:outline-none"
              style={{
                fontSize: `${fontSize}px`,
                lineHeight: '1.25rem',
                whiteSpace: wrap ? 'pre-wrap' : 'pre',
              }}
              value={content}
              onChange={(e) => onChange(e.target.value)}
              onScroll={handleScroll}
              onClick={updateCursorInfo}
              onKeyUp={updateCursorInfo}
              onSelect={updateCursorInfo}
              onKeyDown={(e) => {
                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
                  e.preventDefault()
                  handleSave()
                }
              }}
              spellCheck={false}
              disabled={busy || saving}
            />
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-neutral-800 bg-neutral-950/80 px-3 py-2 text-[11px] text-neutral-400">
          <div className="flex flex-wrap items-center gap-3">
            <span className={dirty ? 'text-amber-300' : 'text-neutral-400'}>
              {dirty ? 'Есть несохранённые изменения' : 'Изменений нет'}
            </span>
            <span className="text-neutral-500">Ln {cursorInfo.line}, Col {cursorInfo.column}</span>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <span>{lineCount} lines</span>
            <span>{content.length} chars</span>
          </div>
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
            onClick={handleSave}
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
