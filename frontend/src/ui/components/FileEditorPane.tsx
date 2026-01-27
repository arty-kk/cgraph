// frontend/src/ui/components/FileEditorPane.tsx
import React from 'react'
import { DiffEditor, Editor } from '@monaco-editor/react'
import type { editor, IPosition } from 'monaco-editor'

export type FileEditorPaneProps = {
  open: boolean
  path: string | null
  original: string
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

export function FileEditorPane({
  open,
  path,
  original,
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
}: FileEditorPaneProps) {
  const [wrap, setWrap] = React.useState(true)
  const [fontSize, setFontSize] = React.useState(13)
  const [showDiff, setShowDiff] = React.useState(false)
  const [cursorInfo, setCursorInfo] = React.useState({ line: 1, column: 1 })
  const lineCount = React.useMemo(() => content.split('\n').length || 1, [content])
  const language = React.useMemo(() => {
    if (!path) return 'plaintext'
    const ext = path.split('.').pop()?.toLowerCase()
    switch (ext) {
      case 'ts':
      case 'tsx':
        return 'typescript'
      case 'js':
      case 'jsx':
        return 'javascript'
      case 'json':
        return 'json'
      case 'md':
      case 'markdown':
        return 'markdown'
      case 'yml':
      case 'yaml':
        return 'yaml'
      case 'toml':
        return 'toml'
      case 'py':
        return 'python'
      case 'go':
        return 'go'
      case 'rs':
        return 'rust'
      case 'java':
        return 'java'
      case 'kt':
        return 'kotlin'
      case 'swift':
        return 'swift'
      case 'rb':
        return 'ruby'
      case 'php':
        return 'php'
      case 'cs':
        return 'csharp'
      case 'c':
      case 'h':
        return 'c'
      case 'cpp':
      case 'cc':
      case 'hpp':
        return 'cpp'
      case 'html':
        return 'html'
      case 'css':
        return 'css'
      case 'scss':
      case 'sass':
        return 'scss'
      case 'sql':
        return 'sql'
      case 'sh':
      case 'bash':
        return 'shell'
      case 'xml':
        return 'xml'
      default:
        return 'plaintext'
    }
  }, [path])

  React.useEffect(() => {
    setCursorInfo({ line: 1, column: 1 })
  }, [path, open])

  const updateCursorInfo = React.useCallback((position?: IPosition | null) => {
    if (!position) return
    setCursorInfo({ line: position.lineNumber, column: position.column })
  }, [])

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

  const editorOptions = React.useMemo<editor.IStandaloneEditorConstructionOptions>(() => ({
    readOnly: busy || saving,
    fontSize,
    wordWrap: wrap ? 'on' : 'off',
    minimap: { enabled: false },
    renderWhitespace: 'selection',
    automaticLayout: true,
    scrollBeyondLastLine: false,
  }), [busy, saving, fontSize, wrap])

  const handleEditorMount = React.useCallback((instance: editor.IStandaloneCodeEditor, monaco: typeof import('monaco-editor')) => {
    updateCursorInfo(instance.getPosition())
    instance.onDidChangeCursorPosition((e) => updateCursorInfo(e.position))
    instance.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      handleSave()
    })
  }, [handleSave, updateCursorInfo])

  const handleDiffMount = React.useCallback((instance: editor.IStandaloneDiffEditor, monaco: typeof import('monaco-editor')) => {
    const modified = instance.getModifiedEditor()
    updateCursorInfo(modified.getPosition())
    modified.onDidChangeCursorPosition((e) => updateCursorInfo(e.position))
    modified.onDidChangeModelContent(() => {
      const model = modified.getModel()
      onChange(model?.getValue() ?? '')
    })
    modified.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      handleSave()
    })
  }, [handleSave, onChange, updateCursorInfo])

  return (
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
          <button
            type="button"
            className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
            onClick={onClose}
            disabled={saving}
          >
            Back to graph
          </button>
          {path && (
            <div className="flex items-center gap-2 min-w-0">
              <span className="max-w-[52vw] truncate text-neutral-100">{path}</span>
              {dirty && (
                <span
                  className="inline-flex items-center gap-1 rounded-full border border-amber-400/60 bg-amber-500/15 px-2 py-0.5 text-[10px] font-semibold text-amber-200"
                  aria-label="Unsaved changes"
                  title="Unsaved changes"
                >
                  ● Unsaved
                </span>
              )}
            </div>
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
            onClick={() => setShowDiff((prev) => !prev)}
          >
            {showDiff ? 'Diff on' : 'Diff off'}
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
        <div className="min-h-[60vh]">
          {showDiff ? (
            <DiffEditor
              height="60vh"
              language={language}
              original={original}
              modified={content}
              options={{
                ...editorOptions,
                renderSideBySide: true,
              }}
              onMount={handleDiffMount}
              theme="vs-dark"
            />
          ) : (
            <Editor
              height="60vh"
              language={language}
              value={content}
              onChange={(value) => onChange(value ?? '')}
              options={editorOptions}
              onMount={handleEditorMount}
              theme="vs-dark"
            />
          )}
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
  )
}
