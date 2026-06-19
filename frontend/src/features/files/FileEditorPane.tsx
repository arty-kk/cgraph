// frontend/src/ui/components/FileEditorPane.tsx
import React from 'react'
import { DiffEditor, Editor } from '@monaco-editor/react'
import type { editor, IPosition } from 'monaco-editor'
import type { NodeInfo, ProjectFileItem } from '@/api'
import { useFileEditorPaneState } from './useFileEditorPaneState'
import { FileDependenciesPanel } from './FileDependenciesPanel'

export type FileEditorPaneProps = {
  open: boolean
  path: string | null
  tabs: Array<{ path: string; dirty: boolean }>
  activePath: string | null
  nodeInfo?: NodeInfo | null
  fileMeta?: ProjectFileItem | null
  dependencies?: { in: string[]; out: string[] }
  dependencyMeta?: {
    truncated_in?: boolean
    truncated_out?: boolean
    next_cursor_in?: string | null
    next_cursor_out?: string | null
  } | null
  showDependencies?: boolean
  totalIn?: number
  totalOut?: number
  saveBanner?: {
    status: 'ok' | 'rescan_scheduled' | 'failed'
    warnings: string[]
    rollback?: string
    conflict?: boolean
    conflictReason?: string
    error?: string
    rescanTask?: { task_id?: string; status?: string }
    metricsPending?: boolean
  } | null
  draftCount?: number
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
  onLoadMoreDependencies?: () => void
  onRescan?: () => void
  onClearDrafts?: () => void
}

export function FileEditorPane(props: FileEditorPaneProps) {
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

  const {
    tabScrollRef, cursorInfo, tabOverflowState, depsOpen, setDepsOpen, lineCount, language,
    editorOptions, updateTabOverflowState, getShortPath, handleEditorMount, handleDiffMount,
    handleScrollTabs, saveViewStateForPath,
    DEP_LIMIT, contextFanIn, contextFanOut, contextLoc, contextRisk, depButtonClass, depsCanLoadMore, depsIn, depsOut, depsTruncated, formatContextValue, handleCopyPath, handleSave, readOnly, readOnlyTooltip, saveWarnings, showContext, showDependenciesBlock, totalInCount, totalOutCount,
  } = useFileEditorPaneState(props)
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
        <FileDependenciesPanel
          path={path}
          depsIn={depsIn}
          depsOut={depsOut}
          totalInCount={totalInCount}
          totalOutCount={totalOutCount}
          depButtonClass={depButtonClass}
          depsCanLoadMore={depsCanLoadMore}
          depsTruncated={depsTruncated}
          DEP_LIMIT={DEP_LIMIT}
          dependencyMeta={dependencyMeta}
          depsOpen={depsOpen}
          setDepsOpen={setDepsOpen}
          onOpenDependencyInGraph={onOpenDependencyInGraph}
          onOpenDependencyFile={onOpenDependencyFile}
          onLoadMoreDependencies={onLoadMoreDependencies}
        />
      )}
      {saveBanner && (
        <div className="rounded-md border border-amber-800/70 bg-amber-950/40 px-3 py-2 text-[11px] text-amber-200">
          <div className="font-semibold">
            {saveBanner.status === 'failed'
              ? 'Indexing failed'
              : 'Indexing incomplete — rescan recommended'}
          </div>
          {saveWarnings.length > 0 && (
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[10px] text-amber-100">
              {saveWarnings.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          )}
          {saveBanner.conflictReason && (
            <div className="mt-1 text-[10px] text-amber-100">
              Conflict: {saveBanner.conflictReason.replace(/_/g, ' ')}
            </div>
          )}
          {saveBanner.metricsPending && (
            <div className="mt-1 text-[10px] text-amber-100">
              Graph metrics recomputation is running in the background.
            </div>
          )}
          {saveBanner.error && (
            <div className="mt-1 text-[10px] text-amber-100">Error: {saveBanner.error}</div>
          )}
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              className="rounded-md border border-amber-800/70 bg-amber-900/40 px-2 py-1 text-[10px] font-semibold text-amber-100 hover:bg-amber-900/60 disabled:opacity-50"
              onClick={() => onRescan?.()}
              disabled={!onRescan}
            >
              Rescan now
            </button>
            {(saveBanner.conflict || saveBanner.rollback === 'failed') && (
              <button
                type="button"
                className="rounded-md border border-amber-800/70 bg-amber-900/40 px-2 py-1 text-[10px] font-semibold text-amber-100 hover:bg-amber-900/60"
                onClick={() => void onReload()}
              >
                Reload file
              </button>
            )}
          </div>
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
          className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-xs font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
          onClick={() => onClearDrafts?.()}
          disabled={draftCount <= 0 || !onClearDrafts}
          title="Clear stored drafts"
        >
          Clear drafts
        </button>
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
