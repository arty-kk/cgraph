import React, { useMemo } from 'react'
import type { NodeSearchItem } from '@/api'
import { LanguageIcon } from '@/shared/ui/LanguageIcon'
import type { Item, Props } from './commandItems'

function norm(x: string) {
  return (x || '').trim().toLowerCase()
}

export function useCommandSources(props: Props, qNorm: string, files: NodeSearchItem[]) {
  const {
    projects, activeProject, onPickProject, onClose, pinnedPaths, openFilePaths,
    selectionTrail, selectedPath, onSelectPath, onOpenFileEditor,
  } = props
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
  return { projectItems, fileItems, pinnedItems, openedItems, recentItems }
}
