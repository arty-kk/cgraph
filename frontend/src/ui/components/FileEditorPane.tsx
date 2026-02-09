// frontend/src/ui/components/FileEditorPane.tsx
import React from 'react'
import { DiffEditor, Editor } from '@monaco-editor/react'
import type { editor, IPosition } from 'monaco-editor'
import type { NodeInfo, ProjectFileItem } from '../../api'
import { safeStorageGet, safeStorageSet } from '../../lib/storage'

export type FileEditorPaneProps = {
  open: boolean
  path: string | null
  tabs: Array<{ path: string; dirty: boolean }>
  activePath: string | null
  nodeInfo?: NodeInfo | null
  fileMeta?: ProjectFileItem | null
  dependencies?: { in: string[]; out: string[] }
  showDependencies?: boolean
  totalIn?: number
  totalOut?: number
  original: string
  content: string
  busy: boolean
  saving: boolean
  dirty: boolean
  truncated: boolean
  error: string | null
  wrap: boolean
  showDiff: boolean
  fontSize: number
  pendingJump?: { path: string; line: number; column: number } | null
  gotoLineRequestId?: number
  findRequestId?: number
  replaceRequestId?: number
  outlineRequestId?: number
  onApplyPendingJump?: () => void
  onSelectTab: (path: string) => void
  onCloseTab: (path: string) => void
  onChange: (value: string) => void
  onReload: () => void | Promise<void>
  onSave: () => void | Promise<boolean>
  onClose: () => void
  onToggleWrap: () => void
  onToggleDiff: () => void
  onSetFontSize: (value: number) => void
  onFindInFile: () => void
  onReplaceInFile: () => void
  onGoToSymbol: () => void
  onOpenInGraph: (path: string) => void
  onOpenDependencyInGraph: (path: string) => void
  onOpenDependencyFile: (path: string) => void
}

export function FileEditorPane({
  open,
  path,
  tabs,
  activePath,
  nodeInfo,
  fileMeta,
  dependencies,
  showDependencies,
  totalIn,
  totalOut,
  original,
  content,
  busy,
  saving,
  dirty,
  truncated,
  error,
  wrap,
  showDiff,
  fontSize,
  pendingJump,
  gotoLineRequestId,
  findRequestId,
  replaceRequestId,
  outlineRequestId,
  onApplyPendingJump,
  onSelectTab,
  onCloseTab,
  onChange,
  onReload,
  onSave,
  onClose,
  onToggleWrap,
  onToggleDiff,
  onSetFontSize,
  onFindInFile,
  onReplaceInFile,
  onGoToSymbol,
  onOpenInGraph,
  onOpenDependencyInGraph,
  onOpenDependencyFile,
}: FileEditorPaneProps) {
  const [cursorInfo, setCursorInfo] = React.useState({ line: 1, column: 1 })
  const editorRef = React.useRef<editor.IStandaloneCodeEditor | null>(null)
  const diffEditorRef = React.useRef<editor.IStandaloneDiffEditor | null>(null)
  const monacoRef = React.useRef<typeof import('monaco-editor') | null>(null)
  const tabScrollRef = React.useRef<HTMLDivElement | null>(null)
  const viewStateByPathRef = React.useRef<Map<string, editor.ICodeEditorViewState | null>>(new Map())
  const prevActivePathRef = React.useRef<string | null>(null)
  const [editorReadyTick, setEditorReadyTick] = React.useState(0)
  const [tabOverflowState, setTabOverflowState] = React.useState({
    hasOverflow: false,
    canScrollLeft: false,
    canScrollRight: false,
  })
  const [depsOpen, setDepsOpen] = React.useState(() => {
    return (safeStorageGet('cs.editor.depsOpen', '') || '') === '1'
  })
  const lineCount = React.useMemo(() => content.split('\n').length || 1, [content])
  const readOnly = busy || saving || truncated
  const readOnlyTooltip = 'Editing is locked due to read-only mode or large file'
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

  React.useEffect(() => {
    if (!pendingJump || !path || busy) return
    if (pendingJump.path !== path) return
    const target = showDiff ? diffEditorRef.current?.getModifiedEditor() : editorRef.current
    if (!target) return
    const position = {
      lineNumber: Math.max(1, pendingJump.line),
      column: Math.max(1, pendingJump.column),
    }
    target.setPosition(position)
    target.revealPositionInCenter(position)
    target.focus()
    onApplyPendingJump?.()
  }, [busy, editorReadyTick, onApplyPendingJump, path, pendingJump, showDiff])

  React.useEffect(() => {
    safeStorageSet('cs.editor.depsOpen', depsOpen ? '1' : '0')
  }, [depsOpen])

  const updateCursorInfo = React.useCallback((position?: IPosition | null) => {
    if (!position) return
    setCursorInfo({ line: position.lineNumber, column: position.column })
  }, [])

  const updateTabOverflowState = React.useCallback(() => {
    const container = tabScrollRef.current
    if (!container) {
      setTabOverflowState({ hasOverflow: false, canScrollLeft: false, canScrollRight: false })
      return
    }
    const { scrollLeft, scrollWidth, clientWidth } = container
    const hasOverflow = scrollWidth > clientWidth + 1
    const canScrollLeft = scrollLeft > 0
    const canScrollRight = scrollLeft + clientWidth < scrollWidth - 1
    setTabOverflowState({ hasOverflow, canScrollLeft, canScrollRight })
  }, [])

  const getActiveEditor = React.useCallback(() => {
    return showDiff ? diffEditorRef.current?.getModifiedEditor() ?? null : editorRef.current
  }, [showDiff])

  const saveViewStateForPath = React.useCallback((targetPath: string | null) => {
    if (!targetPath) return
    const editorInstance = getActiveEditor()
    if (!editorInstance) return
    viewStateByPathRef.current.set(targetPath, editorInstance.saveViewState())
  }, [getActiveEditor])

  const restoreViewStateForPath = React.useCallback((targetPath: string | null) => {
    if (!targetPath) return
    const editorInstance = getActiveEditor()
    if (!editorInstance) return
    const state = viewStateByPathRef.current.get(targetPath)
    if (!state) return
    editorInstance.restoreViewState(state)
    const position = editorInstance.getPosition()
    if (position) {
      editorInstance.revealPositionInCenter(position)
    }
    editorInstance.focus()
  }, [getActiveEditor])

  React.useEffect(() => {
    const container = tabScrollRef.current
    if (!container) return undefined
    updateTabOverflowState()
    const observer = new ResizeObserver(() => updateTabOverflowState())
    observer.observe(container)
    return () => observer.disconnect()
  }, [tabs.length, updateTabOverflowState])

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

  const handleScrollTabs = (direction: -1 | 1) => {
    const container = tabScrollRef.current
    if (!container) return
    container.scrollBy({ left: direction * container.clientWidth * 0.5, behavior: 'smooth' })
  }

  const getShortPath = React.useCallback((fullPath: string) => {
    const segments = fullPath.split('/').filter(Boolean)
    const tail = segments.slice(-3)
    const shortPath = tail.join('/')
    return segments.length > tail.length ? `…/${shortPath}` : shortPath
  }, [])

  const editorOptions = React.useMemo<editor.IStandaloneEditorConstructionOptions>(() => ({
    readOnly,
    fontSize,
    wordWrap: wrap ? 'on' : 'off',
    minimap: { enabled: false },
    renderWhitespace: 'selection',
    automaticLayout: true,
    scrollBeyondLastLine: false,
  }), [readOnly, fontSize, wrap])

  const runEditorAction = React.useCallback((actionId: string) => {
    const target = diffEditorRef.current?.getModifiedEditor() ?? editorRef.current
    if (!target) return false
    const action = target.getAction(actionId)
    if (!action) return false
    void action.run()
    target.focus()
    return true
  }, [])

  React.useEffect(() => {
    if (!gotoLineRequestId) return
    runEditorAction('editor.action.gotoLine')
  }, [gotoLineRequestId, runEditorAction])

  React.useEffect(() => {
    if (!findRequestId) return
    runEditorAction('editor.action.find')
  }, [findRequestId, runEditorAction])

  React.useEffect(() => {
    if (!replaceRequestId) return
    runEditorAction('editor.action.startFindReplaceAction')
  }, [replaceRequestId, runEditorAction])

  React.useEffect(() => {
    if (!outlineRequestId) return
    runEditorAction('editor.action.quickOutline')
  }, [outlineRequestId, runEditorAction])

  const handleEditorMount = React.useCallback((instance: editor.IStandaloneCodeEditor, monaco: typeof import('monaco-editor')) => {
    editorRef.current = instance
    monacoRef.current = monaco
    setEditorReadyTick((tick) => tick + 1)
    updateCursorInfo(instance.getPosition())
    instance.onDidChangeCursorPosition((e) => updateCursorInfo(e.position))
    instance.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      handleSave()
    })
    restoreViewStateForPath(activePath)
  }, [activePath, handleSave, restoreViewStateForPath, updateCursorInfo])

  const handleDiffMount = React.useCallback((instance: editor.IStandaloneDiffEditor, monaco: typeof import('monaco-editor')) => {
    diffEditorRef.current = instance
    monacoRef.current = monaco
    setEditorReadyTick((tick) => tick + 1)
    const modified = instance.getModifiedEditor()
    updateCursorInfo(modified.getPosition())
    modified.onDidChangeCursorPosition((e) => updateCursorInfo(e.position))
    modified.onDidChangeModelContent(() => {
      const model = modified.getModel()
      if (!model) return
      onChange(model.getValue())
    })
    modified.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => {
      handleSave()
    })
    restoreViewStateForPath(activePath)
  }, [activePath, handleSave, onChange, restoreViewStateForPath, updateCursorInfo])

  React.useEffect(() => {
    const diffEditor = diffEditorRef.current
    if (!diffEditor) return
    diffEditor.getModifiedEditor().updateOptions({ readOnly })
  }, [readOnly])

  React.useEffect(() => {
    const previousPath = prevActivePathRef.current
    if (previousPath && previousPath !== activePath) {
      saveViewStateForPath(previousPath)
    }
    prevActivePathRef.current = activePath
  }, [activePath, saveViewStateForPath])

  React.useEffect(() => {
    if (!activePath) return
    restoreViewStateForPath(activePath)
  }, [activePath, editorReadyTick, restoreViewStateForPath, showDiff])

  React.useEffect(() => {
    return () => {
      saveViewStateForPath(activePath)
    }
  }, [activePath, saveViewStateForPath])

  const nodeInfoMatchesPath = Boolean(path && nodeInfo?.path && nodeInfo.path === path)
  const fileMetaMatchesPath = Boolean(path && fileMeta?.path && fileMeta.path === path)
  const showContext = nodeInfoMatchesPath || fileMetaMatchesPath
  const contextRisk = fileMetaMatchesPath ? fileMeta?.risk : null
  const contextLoc = nodeInfoMatchesPath ? nodeInfo?.loc : null
  const contextFanIn = nodeInfoMatchesPath ? nodeInfo?.fan_in : null
  const contextFanOut = nodeInfoMatchesPath ? nodeInfo?.fan_out : null
  const formatContextValue = (value: number | null | undefined) => {
    if (value === null || value === undefined) return '—'
    const numeric = Number(value)
    return Number.isFinite(numeric) ? String(value) : '—'
  }
  const DEP_LIMIT = 20
  const depsIn = dependencies?.in ?? []
  const depsOut = dependencies?.out ?? []
  const totalInCount = typeof totalIn === 'number' ? totalIn : depsIn.length
  const totalOutCount = typeof totalOut === 'number' ? totalOut : depsOut.length
  const showDependenciesBlock = showDependencies !== false && Boolean(dependencies)
  const depButtonClass =
    'rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[10px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50'

  return (
    <div className="flex flex-col gap-3 h-full min-h-0">
      {tabs.length > 0 && (
        <div className="flex items-center gap-2 border-b border-neutral-800 bg-neutral-950/80 px-2 py-1 text-[11px]">
          {tabOverflowState.hasOverflow && tabOverflowState.canScrollLeft && (
            <button
              type="button"
              className="rounded-md border border-neutral-800 bg-neutral-900 px-1.5 py-1 text-[10px] text-neutral-200 hover:bg-neutral-800"
              onClick={() => handleScrollTabs(-1)}
              aria-label="Scroll tabs left"
            >
              ←
            </button>
          )}
          <div
            ref={tabScrollRef}
            onScroll={updateTabOverflowState}
            className="flex min-w-0 flex-1 flex-nowrap items-center gap-2 overflow-x-auto py-0.5"
          >
            {tabs.map((tab) => {
              const name = tab.path.split('/').pop() || tab.path
              const shortPath = getShortPath(tab.path)
              const active = tab.path === activePath
              return (
                <div
                  key={tab.path}
                  className={[
                    'flex shrink-0 items-center gap-2 px-2 py-1 min-w-0 border-b-2',
                    active ? 'border-indigo-500/80 bg-neutral-900/80' : 'border-transparent text-neutral-400',
                  ].join(' ')}
                >
                  <button
                    type="button"
                    className="flex min-w-0 max-w-[18vw] flex-col items-start gap-0.5 text-left text-neutral-200 hover:text-neutral-100"
                    onClick={() => onSelectTab(tab.path)}
                    title={tab.path}
                  >
                    <span className="flex min-w-0 items-center gap-1">
                      <span className="truncate">{name}</span>
                      {tab.dirty && (
                        <span className="text-amber-300" aria-label="Unsaved changes" title="Unsaved changes">●</span>
                      )}
                    </span>
                    <span className="max-w-full truncate text-[10px] text-neutral-500">{shortPath}</span>
                  </button>
                  <button
                    type="button"
                    className="rounded-sm border border-neutral-700 bg-neutral-900 px-1 text-[10px] text-neutral-300 hover:bg-neutral-800"
                    onClick={(e) => {
                      e.stopPropagation()
                      if (tab.path === activePath) {
                        saveViewStateForPath(tab.path)
                      }
                      onCloseTab(tab.path)
                    }}
                    aria-label={`Close ${name}`}
                  >
                    ×
                  </button>
                </div>
              )
            })}
          </div>
          {tabOverflowState.hasOverflow && tabOverflowState.canScrollRight && (
            <button
              type="button"
              className="rounded-md border border-neutral-800 bg-neutral-900 px-1.5 py-1 text-[10px] text-neutral-200 hover:bg-neutral-800"
              onClick={() => handleScrollTabs(1)}
              aria-label="Scroll tabs right"
            >
              →
            </button>
          )}
        </div>
      )}
      {showDependenciesBlock && (
        <div className="rounded-md border border-neutral-800 bg-neutral-950/80 px-3 py-2 text-[11px] text-neutral-300">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] uppercase tracking-[0.2em] text-neutral-500">Dependencies</span>
              <span className="text-[10px] text-neutral-500">In {totalInCount} · Out {totalOutCount}</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className={depButtonClass}
                onClick={() => setDepsOpen((prev) => !prev)}
                aria-expanded={depsOpen}
              >
                {depsOpen ? 'Hide list' : 'Show list'}
              </button>
              <button
                type="button"
                className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
                onClick={() => path && onOpenDependencyInGraph(path)}
                disabled={!path}
              >
                Open in graph
              </button>
            </div>
          </div>
          {depsOpen && (
            <div className="mt-2 grid gap-3 sm:grid-cols-2">
              <div className="space-y-2">
                <div className="flex items-center justify-between text-[10px] text-neutral-500">
                  <span className="uppercase tracking-[0.2em]">In</span>
                  <span className="text-neutral-400">{totalInCount}</span>
                </div>
                <div className="space-y-1">
                  {depsIn.slice(0, DEP_LIMIT).map((depPath) => (
                    <div key={`dep-in-${depPath}`} className="flex items-center justify-between gap-2">
                      <span className="min-w-0 flex-1 truncate text-[11px] text-neutral-200" title={depPath}>
                        {depPath}
                      </span>
                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          type="button"
                          className={depButtonClass}
                          onClick={() => onOpenDependencyInGraph(depPath)}
                        >
                          Open in graph
                        </button>
                        <button
                          type="button"
                          className={depButtonClass}
                          onClick={() => onOpenDependencyFile(depPath)}
                        >
                          Open file
                        </button>
                      </div>
                    </div>
                  ))}
                  {!depsIn.length && <div className="text-[11px] text-neutral-500">—</div>}
                </div>
                {depsIn.length > DEP_LIMIT && (
                  <button
                    type="button"
                    className={depButtonClass}
                    onClick={() => path && onOpenDependencyInGraph(path)}
                    disabled={!path}
                  >
                    Show more…
                  </button>
                )}
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between text-[10px] text-neutral-500">
                  <span className="uppercase tracking-[0.2em]">Out</span>
                  <span className="text-neutral-400">{totalOutCount}</span>
                </div>
                <div className="space-y-1">
                  {depsOut.slice(0, DEP_LIMIT).map((depPath) => (
                    <div key={`dep-out-${depPath}`} className="flex items-center justify-between gap-2">
                      <span className="min-w-0 flex-1 truncate text-[11px] text-neutral-200" title={depPath}>
                        {depPath}
                      </span>
                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          type="button"
                          className={depButtonClass}
                          onClick={() => onOpenDependencyInGraph(depPath)}
                        >
                          Open in graph
                        </button>
                        <button
                          type="button"
                          className={depButtonClass}
                          onClick={() => onOpenDependencyFile(depPath)}
                        >
                          Open file
                        </button>
                      </div>
                    </div>
                  ))}
                  {!depsOut.length && <div className="text-[11px] text-neutral-500">—</div>}
                </div>
                {depsOut.length > DEP_LIMIT && (
                  <button
                    type="button"
                    className={depButtonClass}
                    onClick={() => path && onOpenDependencyInGraph(path)}
                    disabled={!path}
                  >
                    Show more…
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      )}
      {error && (
        <div className="rounded-md border border-rose-900/60 bg-rose-950/40 px-3 py-2 text-xs text-rose-200">
          {error}
        </div>
      )}
      {truncated && (
        <div className="rounded-md border border-amber-800/70 bg-amber-950/40 px-3 py-2 text-[11px] text-amber-200">
          File is too large — only a fragment is shown. Saving is disabled.
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-neutral-800 bg-neutral-950/80 px-2 py-1 text-[11px] text-neutral-300">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-neutral-700 bg-neutral-900/80 px-2 py-0.5 text-[10px] uppercase tracking-[0.2em] text-neutral-400">
            Editor
          </span>
          <span className="text-[10px] text-neutral-500">Ctrl/⌘+Shift+G</span>
          <button
            type="button"
            className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
            onClick={onClose}
            disabled={saving}
            title="Back to graph (Ctrl/⌘+Shift+G)"
          >
            Back to graph
          </button>
          {path && (
            <div className="flex items-center gap-2 min-w-0">
              <span className="max-w-[52vw] truncate text-neutral-100">{path}</span>
              {readOnly && (
                <span
                  className="inline-flex items-center gap-1 rounded-full border border-neutral-600/70 bg-neutral-800/80 px-2 py-0.5 text-[10px] font-semibold text-neutral-200"
                  aria-label={readOnlyTooltip}
                  title={readOnlyTooltip}
                >
                  Read-only
                </span>
              )}
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {showContext && (
            <div className="flex flex-wrap items-center gap-2 rounded-md border border-neutral-800 bg-neutral-900/80 px-2 py-1 text-[11px] text-neutral-300">
              <span className="text-[10px] uppercase tracking-[0.2em] text-neutral-500">Context</span>
              <div className="flex flex-wrap items-center gap-2 text-neutral-400">
                <span>
                  Risk <span className="text-neutral-100">{formatContextValue(contextRisk)}</span>
                </span>
                <span>
                  LOC <span className="text-neutral-100">{formatContextValue(contextLoc)}</span>
                </span>
                <span>
                  Fan in <span className="text-neutral-100">{formatContextValue(contextFanIn)}</span>
                </span>
                <span>
                  Fan out <span className="text-neutral-100">{formatContextValue(contextFanOut)}</span>
                </span>
              </div>
            </div>
          )}
          <button
            type="button"
            className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
            onClick={() => path && onOpenInGraph(path)}
            disabled={!path}
          >
            Open in graph
          </button>
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
            onClick={onFindInFile}
            disabled={!path}
          >
            Find
          </button>
          <button
            type="button"
            className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
            onClick={onReplaceInFile}
            disabled={!path}
          >
            Replace
          </button>
          <button
            type="button"
            className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
            onClick={onGoToSymbol}
            disabled={!path}
          >
            Outline
          </button>
          <button
            type="button"
            className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
            onClick={onToggleDiff}
          >
            {showDiff ? 'Hide diff' : 'Show diff'}
          </button>
          <button
            type="button"
            className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
            onClick={onToggleWrap}
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
              onChange={(e) => onSetFontSize(Number(e.target.value))}
              className="h-1 w-20 accent-indigo-500"
              aria-label="Font size"
            />
            <span className="text-[11px] text-neutral-300">{fontSize}px</span>
          </div>
        </div>
      </div>
      <div className="rounded-lg border border-neutral-800 bg-gradient-to-b from-neutral-950 via-neutral-950 to-neutral-900/70 shadow-inner flex flex-col flex-1 min-h-0">
        <div className="flex-1 min-h-0">
          {showDiff ? (
            <DiffEditor
              height="100%"
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
              height="100%"
              language={language}
              value={content}
              onChange={(value) => {
                if (value === undefined) return
                onChange(value)
              }}
              options={editorOptions}
              onMount={handleEditorMount}
              theme="vs-dark"
            />
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-neutral-800 bg-neutral-950/80 px-3 py-2 text-[11px] text-neutral-400 shrink-0">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-neutral-500">Ln {cursorInfo.line}, Col {cursorInfo.column}</span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span>{lineCount} lines</span>
          <span>{content.length} chars</span>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 shrink-0">
        <button
          type="button"
          className="rounded-md bg-neutral-900 hover:bg-neutral-800 border border-neutral-800 px-2 py-1 text-xs font-semibold disabled:opacity-50"
          onClick={() => void onReload()}
          disabled={busy || saving || !path}
        >
          Reload
        </button>
        <button
          type="button"
          className="rounded-md bg-indigo-600 hover:bg-indigo-500 px-2 py-1 text-xs font-semibold disabled:opacity-50"
          onClick={handleSave}
          disabled={busy || saving || !dirty || truncated || !path}
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          className="rounded-md bg-neutral-800 hover:bg-neutral-700 px-2 py-1 text-xs font-semibold disabled:opacity-50"
          onClick={onClose}
          disabled={saving}
        >
          Close
        </button>
      </div>
    </div>
  )
}
