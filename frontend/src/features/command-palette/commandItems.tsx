import React from 'react'
import { useMemo } from 'react'
import type { Project } from '@/api'


export type CmdGroup = 'Project' | 'Graph' | 'UI' | 'Editor' | 'Selection' | 'Navigation'

export type Item = {
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

export type Props = {
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


export function useCommandItems(props: Props): Item[] {
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

  return useMemo<Item[]>(() => {
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
  }, [props])
}
