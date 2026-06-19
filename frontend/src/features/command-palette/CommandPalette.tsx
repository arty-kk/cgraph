//frontend/src/ui/components/CommandPalette.tsx
import React, { useEffect, useMemo, useRef, useState } from 'react'
import type { Project, NodeSearchItem } from '@/api'
import { searchNodes } from '@/api'
import { Modal } from '@/shared/ui/Modal'
import { LanguageIcon } from '@/shared/ui/LanguageIcon'
import { useCommandItems, type Item, type Props, type CmdGroup } from './commandItems'
import { useCommandSources } from './commandSources'

function norm(s: string) {
  return (s || '').trim().toLowerCase()
}

export function CommandPalette(props: Props) {
  const {
    open,
    onClose,
    projects,
    activeProject,
    onPickProject,
    selectedPath,
    onSelectPath,
    onTogglePinPath,
    onOpenFileEditor,
    openFilePaths,
    selectionTrail,
    pinnedPaths,
    onScan,
    onRefresh,
    onOpenDocs,
    focusGraph,
    setFocusGraph,
    onClearSelection,
    canGoBack,
    canGoForward,
    onBack,
    onForward,
    compactMode,
    onToggleCompactMode,
    editorOpen,
    activeFilePath,
    canSave,
    canSaveAll,
    onSave,
    onSaveAll,
    onCloseTab,
    canCloseAllTabs,
    onCloseAllTabs,
    canCloseOtherTabs,
    onCloseOtherTabs,
    canCloseTabsToRight,
    onCloseTabsToRight,
    onToggleWrap,
    onToggleDiff,
    onIncreaseFontSize,
    onDecreaseFontSize,
    onToggleExplorer,
    onToggleWorkspaceView,
    onFindInFile,
    onReplaceInFile,
    onGoToSymbol,
  } = props
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [query, setQuery] = useState('')
  const [files, setFiles] = useState<NodeSearchItem[]>([])
  const [filesBusy, setFilesBusy] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)
  const searchSeqRef = useRef(0)
  const [helpOpen, setHelpOpen] = useState(false)

  const controlBase = 'h-9 rounded-md bg-neutral-900 border border-neutral-800 px-3 text-sm outline-none'
  const controlDisabled = 'disabled:opacity-50'
  const controlClass = `${controlBase} ${controlDisabled}`

  const itemBase = 'w-full text-left rounded-md border px-3 py-2 transition-colors disabled:opacity-50'
  const itemIdle = 'bg-neutral-950 border-neutral-800 hover:border-neutral-700'
  const itemActive = 'bg-indigo-950/40 border-indigo-700'

  const HelpButton = ({ label }: { label?: string }) => (
    <button
      type="button"
      className="w-3.5 h-3.5 rounded-full border border-neutral-800 bg-neutral-900 text-neutral-200 text-[10px] leading-none font-semibold hover:bg-neutral-800 shrink-0"
      onMouseDown={(e) => {
        e.preventDefault()
        e.stopPropagation()
      }}
      onClick={() => setHelpOpen(true)}
      aria-label={label || 'Open help'}
      title={label || 'Help'}
    >
      ?
    </button>
  )

  useEffect(() => {
    if (!open) return
    setQuery('')
    setFiles([])
    setFilesBusy(false)
    setActiveIndex(0)
    const t = window.setTimeout(() => inputRef.current?.focus(), 0)
    return () => window.clearTimeout(t)
  }, [open])

  const qRaw = (query || '').trim()
  const qNorm = norm(query)

  useEffect(() => {
    if (!open) return
    if (!activeProject) {
      searchSeqRef.current += 1
      setFiles([])
      setFilesBusy(false)
      return
    }
    if (qRaw.length < 2) {
      searchSeqRef.current += 1
      setFiles([])
      setFilesBusy(false)
      return
    }

    const seq = ++searchSeqRef.current
    setFilesBusy(true)
    const t = window.setTimeout(async () => {
      try {
        const res = await searchNodes(activeProject.id, qRaw, 20)
        if (searchSeqRef.current !== seq) return
        setFiles(Array.isArray(res) ? res : [])
      } catch {
        if (searchSeqRef.current !== seq) return
        setFiles([])
      } finally {
        if (searchSeqRef.current === seq) setFilesBusy(false)
      }
    }, 180)

    return () => window.clearTimeout(t)
  }, [activeProject?.id, open, qRaw])

  const commandItems = useCommandItems(props)

  const { projectItems, fileItems, pinnedItems, openedItems, recentItems } = useCommandSources(props, qNorm, files)

  const filteredCommands = useMemo(() => {
    if (!qNorm) return commandItems
    return commandItems.filter((it) => norm([it.group, it.title, it.subtitleText, it.hint].filter(Boolean).join(' ')).includes(qNorm))
  }, [commandItems, qNorm])

  type RenderSection = { key: string; title: string; items: Item[]; start: number; note?: string }
  const renderSections: RenderSection[] = useMemo(() => {
    const out: RenderSection[] = []
    let start = 0

    const push = (key: string, title: string, items: Item[], note?: string) => {
      if ((!items || items.length === 0) && !note) return
      out.push({ key, title, items: items || [], start, note })
      start += (items || []).length
    }

    const q = String(qRaw || '').trim()
    const hasQuery = q.length > 0

    const showProjectsSection = !activeProject || hasQuery
    const projectsNote =
      showProjectsSection && projectItems.length === 0
        ? (hasQuery ? 'No projects found.' : 'No projects.')
        : undefined

    if (!activeProject && showProjectsSection) {
      push('projects', 'Projects', projectItems, projectsNote)
    }

    const groupOrder: CmdGroup[] = ['Project', 'Graph', 'UI', 'Editor', 'Selection', 'Navigation']
    for (const g of groupOrder) {
      const items = filteredCommands.filter((c) => c.group === g)
      push(`actions.${g}`, `Actions: ${g}`, items)
    }

    if (activeProject && showProjectsSection) {
      push('projects', 'Projects', projectItems, projectsNote)
    }

    const wantsFiles = q.length >= 2
    const showRecent = q.length < 2

    push('pinned', 'Pinned', pinnedItems)
    push('opened', 'Opened', openedItems)
    if (showRecent) {
      push('recent', 'Recent', recentItems)
    }
    const fileNote =
      !activeProject && wantsFiles
        ? 'Pick a project to search files.'
        : activeProject && wantsFiles && filesBusy
          ? 'Search files…'
          : activeProject && wantsFiles && !filesBusy && fileItems.length === 0
            ? 'No files found.'
            : undefined

    if (wantsFiles || fileItems.length > 0) {
      push('files', 'Files', fileItems, fileNote)
    }

    return out
  }, [
    activeProject,
    fileItems,
    filesBusy,
    filteredCommands,
    openedItems,
    pinnedItems,
    projectItems,
    qRaw,
    recentItems,
  ])

  const itemsFlat: Item[] = useMemo(() => renderSections.flatMap((s) => s.items), [renderSections])

  useEffect(() => {
    if (!open) return
    setActiveIndex((i) => {
      if (itemsFlat.length === 0) return 0
      if (i < 0) return 0
      if (i >= itemsFlat.length) return Math.max(0, itemsFlat.length - 1)
      return i
    })
  }, [itemsFlat.length, open])

  useEffect(() => {
    if (!open) return
    setActiveIndex(0)
  }, [open, qNorm])

  useEffect(() => {
    if (!open) return
    const t = window.setTimeout(() => {
      const el = document.getElementById('cs-cmdp-active') as HTMLElement | null
      if (!el) return
      try {
        el.scrollIntoView({ block: 'nearest' })
      } catch {}
    }, 0)
    return () => window.clearTimeout(t)
  }, [activeIndex, open, itemsFlat.length])

  const onKeyDown = async (e: React.KeyboardEvent) => {
    const len = itemsFlat.length
    if (e.key === 'ArrowDown') {
      if (len === 0) return
      e.preventDefault()
      if (itemsFlat.length === 0) return
      setActiveIndex((i) => Math.min(len - 1, Math.max(0, i + 1)))
      return
    }
    if (e.key === 'ArrowUp') {
      if (len === 0) return
      e.preventDefault()
      if (itemsFlat.length === 0) return
      setActiveIndex((i) => Math.max(0, i - 1))
      return
    }
    if (e.key === 'Enter') {
      e.preventDefault()
      if (len === 0) return
      const item = itemsFlat[activeIndex]
      if (!item || item.disabled) return
      if (e.shiftKey && item.kind === 'file') {
        const path = item.title
        onClose()
        await onSelectPath(path)
        await onTogglePinPath(path)
        if (onOpenFileEditor) {
          await onOpenFileEditor(path)
        }
        return
      }
      await item.onSelect()
      return
    }
  }

  const Section = ({ title }: { title: string }) => (
    <div className="mt-3 text-[11px] uppercase tracking-wide text-neutral-500">{title}</div>
  )

  const ItemRow = ({ item, idx }: { item: Item; idx: number }) => {
    const active = idx === activeIndex
    const tooltip =
      item.kind === 'file'
        ? [item.title, item.subtitleText || '', 'Enter — open in editor', 'Shift+Enter — open + toggle pin'].filter(Boolean).join('\n')
        : [item.title, item.subtitleText || '', item.hint ? `Keys: ${item.hint}` : ''].filter(Boolean).join('\n')
    return (
      <button
        type="button"
        onMouseDown={(e) => e.preventDefault()}
        className={[
          itemBase,
          active ? itemActive : itemIdle,
          item.disabled ? 'opacity-40 cursor-not-allowed' : '',
        ].join(' ')}
        onMouseEnter={() => setActiveIndex(idx)}
        onClick={async () => {
          if (item.disabled) return
          await item.onSelect()
        }}
        disabled={item.disabled}
        title={tooltip}
        id={active ? 'cs-cmdp-active' : undefined}
      >
        <div className="flex items-start gap-3 flex-wrap max-w-full">
          <div className="min-w-0">
            <div className="text-xs font-semibold text-neutral-100 truncate">{item.title}</div>
            {item.subtitle && <div className="text-[11px] text-neutral-500 truncate">{item.subtitle}</div>}
          </div>
          {item.hint ? (
            <div className="shrink-0 text-[11px] text-neutral-400 border border-neutral-800 rounded-md px-2 py-1 bg-neutral-900 whitespace-nowrap">
              {item.hint}
            </div>
          ) : null}
        </div>
      </button>
    )
  }

  const selectionBase = selectedPath ? selectedPath.split('/').pop() || selectedPath : '—'
  const qTrim = String(qRaw || '').trim()
  const hasQuery = qTrim.length > 0
  const inlineHint =
    !activeProject
      ? (hasQuery ? 'Pick a project to enable commands and file search.' : 'Pick a project in the Projects section.')
      : (!hasQuery
          ? 'Start typing to switch projects or find a file.'
          : (qTrim.length < 2 ? 'Files: enter at least 2 characters to search.' : null))

  return (
    <Modal open={open} title="Command palette" onClose={onClose}>
      <div>
        <div className="flex items-center gap-2">
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Command, project, or file path…"
            className={['flex-1', controlClass].join(' ')}
            title="Search commands/projects/files. Files are searched in the active project (min 2 chars)."
          />
          <HelpButton label="Help: Command palette" />
        </div>

        <div className="mt-2 text-[11px] text-neutral-500">
          <span className="text-neutral-600">Project:</span>{' '}
          <span className="text-neutral-300">{activeProject?.name ?? '—'}</span>
          <span className="mx-2 text-neutral-700">·</span>
          <span className="text-neutral-600">Selection:</span>{' '}
          <span className="text-neutral-300" title={selectedPath || ''}>
            {selectionBase}
          </span>
        </div>

        {inlineHint ? <div className="mt-2 text-xs text-amber-300">{inlineHint}</div> : null}

        <div className="mt-3 max-h-[55vh] overflow-auto pr-1 space-y-2">
          {renderSections.map((sec) => (
            <div key={sec.key}>
              <Section title={sec.title} />
              {sec.note ? <div className="mt-2 text-xs text-neutral-500">{sec.note}</div> : null}
              <div className="mt-2 space-y-1.5">
                {sec.items.map((it, i) => (
                  <ItemRow key={it.key} item={it} idx={sec.start + i} />
                ))}
              </div>
            </div>
          ))}

          {renderSections.length === 0 && (
            <div className="text-xs text-neutral-500">Nothing found.</div>
          )}
        </div>

        <div className="mt-4 text-[11px] text-neutral-500 flex flex-wrap gap-x-3 gap-y-1">
          <span>
            <span className="text-neutral-300">Enter</span> — open/run
          </span>
          <span>
            <span className="text-neutral-300">Esc</span> — close
          </span>
          <span>
            <span className="text-neutral-300">↑/↓</span> — navigate
          </span>
          <span>
            <span className="text-neutral-300">Ctrl/⌘+K</span> or{' '}
            <span className="text-neutral-300">Ctrl/⌘+Shift+P</span> — open
          </span>
          <span>
            <span className="text-neutral-300">Shift+Enter</span> — open + toggle pin (file)
          </span>
          <span>
            <span className="text-neutral-300">Ctrl/⌘+Shift+M</span> — compact
          </span>
        </div>

        <Modal open={helpOpen} title="Help: Command palette" onClose={() => setHelpOpen(false)}>
          <div className="space-y-2">
            <div className="text-neutral-200 font-semibold">
              What it is
            </div>
            <div>
              • Command palette provides quick access to actions, project switching, and file search.
            </div>
            <div className="pt-2 text-neutral-200 font-semibold">
              Search
            </div>
            <div>
              • Actions/Projects are filtered locally by your input.
            </div>
            <div>
              • Files are searched via the backend for the active project (<span className="font-mono">min 2 chars</span>).
            </div>
            <div className="text-neutral-400 text-[12px]">
              Tip: for files use a path substring, e.g. <span className="font-mono">service/</span> or a module name.
            </div>

            <div className="pt-2 text-neutral-200 font-semibold">
              Controls
            </div>
            <div>
              • <span className="font-mono">Enter</span> — run an action / pick a project / open a file in the editor.
            </div>
            <div>
              • <span className="font-mono">Shift+Enter</span> on a file — open in the editor and <span className="font-mono">toggle</span> pin (pin/unpin).
            </div>
            <div>
              • <span className="font-mono">↑/↓</span> — move through the list.
            </div>
            <div>
              • <span className="font-mono">Esc</span> — close.
            </div>
            <div className="pt-2 text-neutral-200 font-semibold">
              Groups
            </div>
            <div>
              • Actions are grouped by domain: Project / Graph / UI / Selection / Navigation.
            </div>
            <div>
              • Projects — project list. Appears when you type; if no project is selected, it shows immediately.
              To switch projects with an empty query, just start typing.
            </div>
            <div>
              • Files — file search results. Appears after 2+ characters; search runs in the active project.
              If no project is selected, pick one first.
            </div>
          </div>
        </Modal>
      </div>
    </Modal>
  )
}
