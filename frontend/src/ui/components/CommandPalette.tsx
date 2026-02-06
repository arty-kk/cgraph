//frontend/src/ui/components/CommandPalette.tsx
import React, { useEffect, useMemo, useRef, useState } from 'react'
import type { Project, NodeSearchItem } from '../../api'
import { searchNodes } from '../../api'
import { Modal } from './Modal'
import { LanguageIcon } from './LanguageIcon'

type CmdGroup = 'Project' | 'Graph' | 'UI' | 'Editor' | 'Selection' | 'Navigation'

type Item = {
  key: string
  kind: 'command' | 'project' | 'file'
  title: string
  subtitle?: React.ReactNode
  subtitleText?: string
  group?: CmdGroup
  hint?: string
  disabled?: boolean
  onSelect: () => void | Promise<void>
}

type Props = {
  open: boolean
  onClose: () => void

  projects: Project[]
  activeProject: Project | null
  onPickProject: (p: Project) => void | Promise<void>

  selectedPath: string | null
  onSelectPath: (path: string) => void | Promise<void>
  onTogglePinPath: (path: string) => void | Promise<void>
  onOpenFileEditor?: (path: string) => void | Promise<void>
  openFilePaths: string[]
  selectionTrail: string[]
  pinnedPaths: string[]

  onScan: () => void | Promise<void>
  onRefresh: () => void | Promise<void>
  onOpenDocs: () => void | Promise<void>
  focusGraph: boolean
  setFocusGraph: (v: boolean) => void

  onClearSelection: () => void
  canGoBack: boolean
  canGoForward: boolean
  onBack: () => void
  onForward: () => void

  compactMode: boolean
  onToggleCompactMode: () => void

  editorOpen: boolean
  activeFilePath: string | null
  canSave: boolean
  canSaveAll: boolean
  onSave: () => void | Promise<boolean>
  onSaveAll: () => void | Promise<boolean>
  onCloseTab: (path: string) => void
  canCloseAllTabs: boolean
  onCloseAllTabs: () => void
  canCloseOtherTabs: boolean
  onCloseOtherTabs: (path: string) => void
  canCloseTabsToRight: boolean
  onCloseTabsToRight: (path: string) => void
  onToggleWrap: () => void
  onToggleDiff: () => void
  onIncreaseFontSize: () => void
  onDecreaseFontSize: () => void
  onToggleExplorer: () => void
  onToggleWorkspaceView: () => void
  onFindInFile: () => void
  onReplaceInFile: () => void
  onGoToSymbol: () => void
}

function norm(s: string) {
  return (s || '').trim().toLowerCase()
}

export function CommandPalette({
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
}: Props) {
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

  const commandItems: Item[] = useMemo(() => {
    const hasProject = Boolean(activeProject)
    const hasSel = Boolean(selectedPath)
    const hasActiveFile = Boolean(activeFilePath)

    return [
      {
        key: 'cmd.editor.save',
        kind: 'command',
        group: 'Editor',
        title: 'Save',
        subtitle: 'Save file in editor',
        subtitleText: 'Save file in editor',
        disabled: !hasActiveFile || !canSave,
        onSelect: async () => {
          onClose()
          await onSave()
        },
      },
      {
        key: 'cmd.editor.save.all',
        kind: 'command',
        group: 'Editor',
        title: 'Save all',
        subtitle: 'Save all open files',
        subtitleText: 'Save all open files',
        disabled: !canSaveAll,
        onSelect: async () => {
          onClose()
          await onSaveAll()
        },
      },
      {
        key: 'cmd.editor.close',
        kind: 'command',
        group: 'Editor',
        title: 'Close tab',
        subtitle: 'Close active editor tab',
        subtitleText: 'Close active editor tab',
        disabled: !hasActiveFile,
        onSelect: () => {
          if (!activeFilePath) return
          onClose()
          onCloseTab(activeFilePath)
        },
      },
      {
        key: 'cmd.editor.close.all',
        kind: 'command',
        group: 'Editor',
        title: 'Close all tabs',
        subtitle: 'Close all open tabs',
        subtitleText: 'Close all open tabs',
        disabled: !canCloseAllTabs,
        onSelect: () => {
          onClose()
          onCloseAllTabs()
        },
      },
      {
        key: 'cmd.editor.close.others',
        kind: 'command',
        group: 'Editor',
        title: 'Close other tabs',
        subtitle: 'Close tabs except the active one',
        subtitleText: 'Close tabs except the active one',
        disabled: !hasActiveFile || !canCloseOtherTabs,
        onSelect: () => {
          if (!activeFilePath) return
          onClose()
          onCloseOtherTabs(activeFilePath)
        },
      },
      {
        key: 'cmd.editor.close.right',
        kind: 'command',
        group: 'Editor',
        title: 'Close tabs to the right',
        subtitle: 'Close tabs to the right of the active tab',
        subtitleText: 'Close tabs to the right of the active tab',
        disabled: !hasActiveFile || !canCloseTabsToRight,
        onSelect: () => {
          if (!activeFilePath) return
          onClose()
          onCloseTabsToRight(activeFilePath)
        },
      },
      {
        key: 'cmd.editor.find',
        kind: 'command',
        group: 'Editor',
        hint: 'Ctrl/⌘+F',
        title: 'Find in file',
        subtitle: 'Find text in file',
        subtitleText: 'Find text in file',
        disabled: !editorOpen,
        onSelect: () => {
          onClose()
          onFindInFile()
        },
      },
      {
        key: 'cmd.editor.replace',
        kind: 'command',
        group: 'Editor',
        hint: 'Ctrl/⌘+H',
        title: 'Replace in file',
        subtitle: 'Find and replace in file',
        subtitleText: 'Find and replace in file',
        disabled: !editorOpen,
        onSelect: () => {
          onClose()
          onReplaceInFile()
        },
      },
      {
        key: 'cmd.editor.outline',
        kind: 'command',
        group: 'Editor',
        hint: 'Ctrl/⌘+Shift+O',
        title: 'Go to Symbol',
        subtitle: 'Open outline/symbols list',
        subtitleText: 'Open outline/symbols list',
        disabled: !editorOpen,
        onSelect: () => {
          onClose()
          onGoToSymbol()
        },
      },
      {
        key: 'cmd.editor.wrap',
        kind: 'command',
        group: 'Editor',
        title: 'Toggle wrap',
        subtitle: 'Toggle line wrapping',
        subtitleText: 'Toggle line wrapping',
        disabled: !editorOpen,
        onSelect: () => {
          onClose()
          onToggleWrap()
        },
      },
      {
        key: 'cmd.editor.diff',
        kind: 'command',
        group: 'Editor',
        title: 'Toggle diff',
        subtitle: 'Toggle diff mode',
        subtitleText: 'Toggle diff mode',
        disabled: !editorOpen,
        onSelect: () => {
          onClose()
          onToggleDiff()
        },
      },
      {
        key: 'cmd.editor.font.increase',
        kind: 'command',
        group: 'Editor',
        title: 'Increase font size',
        subtitle: 'Increase editor font size',
        subtitleText: 'Increase editor font size',
        disabled: !editorOpen,
        onSelect: () => {
          onClose()
          onIncreaseFontSize()
        },
      },
      {
        key: 'cmd.editor.font.decrease',
        kind: 'command',
        group: 'Editor',
        title: 'Decrease font size',
        subtitle: 'Decrease editor font size',
        subtitleText: 'Decrease editor font size',
        disabled: !editorOpen,
        onSelect: () => {
          onClose()
          onDecreaseFontSize()
        },
      },
      {
        key: 'cmd.editor.explorer',
        kind: 'command',
        group: 'Editor',
        title: 'Toggle explorer',
        subtitle: 'Show/hide editor sidebar',
        subtitleText: 'Show/hide editor sidebar',
        disabled: !editorOpen,
        onSelect: () => {
          onClose()
          onToggleExplorer()
        },
      },
      {
        key: 'cmd.docs',
        kind: 'command',
        group: 'Project',
        title: 'Open docs',
        subtitle: 'Open generated project docs',
        subtitleText: 'Open generated project docs',
        disabled: !hasProject,
        onSelect: async () => {
          onClose()
          await onOpenDocs()
        },
      },
      {
        key: 'cmd.ui.workspace',
        kind: 'command',
        group: 'UI',
        hint: 'Ctrl/⌘+Shift+G',
        title: 'Toggle workspace view',
        subtitle: 'Switch graph/editor',
        subtitleText: 'Switch graph/editor',
        disabled: false,
        onSelect: () => {
          onClose()
          onToggleWorkspaceView()
        },
      },
      {
        key: 'cmd.ui.compact',
        kind: 'command',
        group: 'UI',
        hint: 'Ctrl/⌘+Shift+M',
        title: compactMode ? 'Disable compact mode' : 'Enable compact mode',
        subtitle: 'Compact labels (tooltips stay)',
        subtitleText: 'Compact labels (tooltips stay)',
        disabled: false,
        onSelect: () => {
          onClose()
          onToggleCompactMode()
        },
      },
      {
        key: 'cmd.scan',
        kind: 'command',
        group: 'Graph',
        title: 'Scan',
        subtitle: 'Index files and recompute dependencies',
        subtitleText: 'Index files and recompute dependencies',
        disabled: !hasProject,
        onSelect: async () => {
          onClose()
          await onScan()
        },
      },
      {
        key: 'cmd.refresh',
        kind: 'command',
        group: 'Graph',
        title: 'Refresh',
        subtitle: 'Reload graph and panel data (without changing project)',
        subtitleText: 'Reload graph and panel data (without changing project)',
        disabled: !hasProject,
        onSelect: async () => {
          onClose()
          await onRefresh()
        },
      },
      {
        key: 'cmd.focus',
        kind: 'command',
        group: 'UI',
        hint: 'F',
        title: focusGraph ? 'Exit focus' : 'Enter focus',
        subtitle: 'Toggle graph focus mode',
        subtitleText: 'Toggle graph focus mode',
        disabled: !hasProject,
        onSelect: () => {
          onClose()
          setFocusGraph(!focusGraph)
        },
      },
      {
        key: 'cmd.pin.selected',
        kind: 'command',
        group: 'Selection',
        title: 'Toggle pin for selection',
        subtitle: 'Pin/unpin selected file',
        subtitleText: 'Pin/unpin selected file',
        disabled: !hasSel,
        onSelect: async () => {
          if (!selectedPath) return
          onClose()
          await onTogglePinPath(selectedPath)
        },
      },
      {
        key: 'cmd.clear',
        kind: 'command',
        group: 'Selection',
        hint: 'Esc',
        title: 'Clear selection',
        subtitle: 'Clear selection (file/node)',
        subtitleText: 'Clear selection (file/node)',
        disabled: !hasSel,
        onSelect: () => {
          onClose()
          onClearSelection()
        },
      },
      {
        key: 'cmd.back',
        kind: 'command',
        group: 'Navigation',
        hint: 'Alt+← / ⌘[',
        title: 'Back',
        subtitle: 'Back in selection history',
        subtitleText: 'Back in selection history',
        disabled: !canGoBack,
        onSelect: () => {
          onClose()
          onBack()
        },
      },
      {
        key: 'cmd.forward',
        kind: 'command',
        group: 'Navigation',
        hint: 'Alt+→ / ⌘]',
        title: 'Forward',
        subtitle: 'Forward in selection history',
        subtitleText: 'Forward in selection history',
        disabled: !canGoForward,
        onSelect: () => {
          onClose()
          onForward()
        },
      },
    ]
  }, [
    activeProject,
    activeFilePath,
    canSave,
    compactMode,
    canGoBack,
    canGoForward,
    editorOpen,
    focusGraph,
    onBack,
    onClearSelection,
    onCloseTab,
    onClose,
    onDecreaseFontSize,
    onIncreaseFontSize,
    onFindInFile,
    onReplaceInFile,
    onGoToSymbol,
    onOpenDocs,
    onToggleCompactMode,
    onToggleDiff,
    onToggleExplorer,
    onToggleWorkspaceView,
    onForward,
    onRefresh,
    onScan,
    onSave,
    selectedPath,
    setFocusGraph,
    onTogglePinPath,
    onToggleWrap,
  ])

  const projectItems: Item[] = useMemo(() => {
    const list = projects
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((p) => {
        const sourceLabel = p.source?.label ?? p.root_path ?? ''
        return {
          key: `proj.${p.id}`,
          kind: 'project' as const,
          title: p.name,
          subtitle: sourceLabel,
          subtitleText: sourceLabel,
          disabled: Boolean(activeProject && p.id === activeProject.id),
          onSelect: async () => {
            onClose()
            await onPickProject(p)
          },
        }
      })

    if (!qNorm) return list.slice(0, 10)
    return list.filter((it) => norm(it.title + ' ' + (it.subtitleText || '')).includes(qNorm)).slice(0, 10)
  }, [activeProject, onClose, onPickProject, projects, qNorm])

  const fileItems: Item[] = useMemo(() => {
    if (!activeProject) return []
    return files.slice(0, 20).map((f) => ({
      key: `file.${f.path}`,
      kind: 'file' as const,
      title: f.path,
      subtitle: (
        <span className="inline-flex items-center gap-1">
          <LanguageIcon language={f.language} className="h-3.5 w-3.5 text-neutral-400" />
          <span>· in:{f.fan_in ?? 0} · out:{f.fan_out ?? 0}</span>
        </span>
      ),
      subtitleText: `${f.language ?? '—'} · in:${f.fan_in ?? 0} · out:${f.fan_out ?? 0}`,
      disabled: false,
      onSelect: async () => {
        onClose()
        await onSelectPath(f.path)
        if (onOpenFileEditor) {
          await onOpenFileEditor(f.path)
        }
      },
    }))
  }, [activeProject, files, onClose, onOpenFileEditor, onSelectPath])

  const pinnedFiles = useMemo(() => {
    const seen = new Set<string>()
    const out: string[] = []
    for (const path of pinnedPaths || []) {
      const p = String(path || '').trim()
      if (!p || seen.has(p)) continue
      seen.add(p)
      out.push(p)
    }
    return out
  }, [pinnedPaths])

  const openedFiles = useMemo(() => {
    const seen = new Set<string>(pinnedFiles)
    const out: string[] = []
    for (const path of openFilePaths || []) {
      const p = String(path || '').trim()
      if (!p || seen.has(p)) continue
      seen.add(p)
      out.push(p)
    }
    return out
  }, [openFilePaths, pinnedFiles])

  const recentFiles = useMemo(() => {
    const seen = new Set<string>([...pinnedFiles, ...openedFiles])
    const filtered: string[] = []
    for (const path of selectionTrail || []) {
      const p = String(path || '').trim()
      if (!p || seen.has(p)) continue
      seen.add(p)
      filtered.push(p)
    }
    return filtered.reverse().slice(0, 10)
  }, [openedFiles, pinnedFiles, selectionTrail])

  const onSelectFilePath = React.useCallback(async (path: string) => {
    onClose()
    if (selectedPath !== path) {
      await onSelectPath(path)
    }
    if (onOpenFileEditor) {
      await onOpenFileEditor(path)
    }
  }, [onClose, onOpenFileEditor, onSelectPath, selectedPath])

  const pinnedItems = useMemo(() => {
    return pinnedFiles.map((path) => ({
      key: `pinned.${path}`,
      kind: 'file' as const,
      title: path,
      disabled: false,
      onSelect: () => onSelectFilePath(path),
    }))
  }, [onSelectFilePath, pinnedFiles])

  const openedItems = useMemo(() => {
    return openedFiles.map((path) => ({
      key: `opened.${path}`,
      kind: 'file' as const,
      title: path,
      disabled: false,
      onSelect: () => onSelectFilePath(path),
    }))
  }, [onSelectFilePath, openedFiles])

  const recentItems = useMemo(() => {
    return recentFiles.map((path) => ({
      key: `recent.${path}`,
      kind: 'file' as const,
      title: path,
      disabled: false,
      onSelect: () => onSelectFilePath(path),
    }))
  }, [onSelectFilePath, recentFiles])

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
