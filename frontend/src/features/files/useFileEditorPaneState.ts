import React from 'react'
import type { editor, IPosition } from 'monaco-editor'
import { safeStorageGet, safeStorageSet } from '@/shared/lib/storage'
import type { FileEditorPaneProps } from './FileEditorPane'

export function useFileEditorPaneState(props: FileEditorPaneProps) {
  const {
  open,
  path,
  tabs,
  activePath,
  nodeInfo,
  fileMeta,
  dependencies,
  dependencyMeta,
  showDependencies,
  totalIn,
  totalOut,
  saveBanner,
  draftCount = 0,
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
  onLoadMoreDependencies,
  onRescan,
  onClearDrafts,
  } = props

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
  const depsTruncated = Boolean(dependencyMeta?.truncated_in || dependencyMeta?.truncated_out)
  const depsCanLoadMore = Boolean(dependencyMeta?.next_cursor_in || dependencyMeta?.next_cursor_out)
  const showDependenciesBlock = showDependencies !== false && Boolean(dependencies)
  const depButtonClass =
    'rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[10px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50'
  const warningMap: Record<string, string> = {
    scan_aborted: 'Scan aborted due to a snapshot mismatch.',
    scan_failed: 'Indexing failed; rescan is recommended.',
    rollback_ok: 'Changes were rolled back.',
    rollback_skipped: 'Rollback skipped due to concurrent changes.',
    rollback_failed: 'Rollback failed; data may be inconsistent.',
  }
  const saveWarnings = (saveBanner?.warnings || []).map((code) => warningMap[code] || code)


  return {
    editorRef, diffEditorRef, monacoRef, tabScrollRef,
    cursorInfo, editorReadyTick, tabOverflowState, depsOpen, setDepsOpen,
    lineCount, language, editorOptions,
    updateTabOverflowState, getShortPath, runEditorAction,
    handleEditorMount, handleDiffMount, handleScrollTabs, saveViewStateForPath,
    DEP_LIMIT, contextFanIn, contextFanOut, contextLoc, contextRisk, depButtonClass, depsCanLoadMore, depsIn, depsOut, depsTruncated, formatContextValue, handleCopyPath, handleSave, readOnly, readOnlyTooltip, saveWarnings, showContext, showDependenciesBlock, totalInCount, totalOutCount,
  }
}
