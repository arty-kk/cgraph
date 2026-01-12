//frontend/src/ui/components/CommandPalette.tsx
import React, { useEffect, useMemo, useRef, useState } from 'react'
import type { Project, NodeSearchItem } from '../../api'
import { searchNodes } from '../../api'
import { Modal } from './Modal'

type CmdGroup = 'Project' | 'Graph' | 'UI' | 'Selection' | 'Navigation'

type Item = {
  key: string
  kind: 'command' | 'project' | 'file'
  title: string
  subtitle?: string
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
      aria-label={label || 'Открыть подсказку'}
      title={label || 'Подсказка'}
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

    return [
      {
        key: 'cmd.docs',
        kind: 'command',
        group: 'Project',
        title: 'Open docs',
        subtitle: 'Открыть сгенерированную документацию проекта',
        disabled: !hasProject,
        onSelect: async () => {
          onClose()
          await onOpenDocs()
        },
      },
      {
        key: 'cmd.ui.compact',
        kind: 'command',
        group: 'UI',
        hint: 'Ctrl/⌘+Shift+M',
        title: compactMode ? 'Disable compact mode' : 'Enable compact mode',
        subtitle: 'Сократить подписи (tooltips остаются)',
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
        subtitle: 'Проиндексировать файлы и пересчитать зависимости',
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
        subtitle: 'Перезагрузить данные графа и панелей (без смены проекта)',
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
        subtitle: 'Переключить режим фокуса на графе',
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
        subtitle: 'Закрепить/открепить выбранный файл',
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
        subtitle: 'Снять выделение (файл/узел)',
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
        subtitle: 'Назад по истории выделений',
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
        subtitle: 'Вперёд по истории выделений',
        disabled: !canGoForward,
        onSelect: () => {
          onClose()
          onForward()
        },
      },
    ]
  }, [
    activeProject,
    compactMode,
    canGoBack,
    canGoForward,
    focusGraph,
    onBack,
    onClearSelection,
    onClose,
    onOpenDocs,
    onToggleCompactMode,
    onForward,
    onRefresh,
    onScan,
    selectedPath,
    setFocusGraph,
    onTogglePinPath,
  ])

  const projectItems: Item[] = useMemo(() => {
    const list = projects
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((p) => ({
        key: `proj.${p.id}`,
        kind: 'project' as const,
        title: p.name,
        subtitle: p.root_path,
        disabled: Boolean(activeProject && p.id === activeProject.id),
        onSelect: async () => {
          onClose()
          await onPickProject(p)
        },
      }))

    if (!qNorm) return list.slice(0, 10)
    return list.filter((it) => norm(it.title + ' ' + (it.subtitle || '')).includes(qNorm)).slice(0, 10)
  }, [activeProject, onClose, onPickProject, projects, qNorm])

  const fileItems: Item[] = useMemo(() => {
    if (!activeProject) return []
    return files.slice(0, 20).map((f) => ({
      key: `file.${f.path}`,
      kind: 'file' as const,
      title: f.path,
      subtitle: `${f.language ?? '—'} · in:${f.fan_in ?? 0} · out:${f.fan_out ?? 0}`,
      disabled: false,
      onSelect: async () => {
        onClose()
        await onSelectPath(f.path)
      },
    }))
  }, [activeProject, files, onClose, onSelectPath])

  const filteredCommands = useMemo(() => {
    if (!qNorm) return commandItems
    return commandItems.filter((it) => norm([it.group, it.title, it.subtitle, it.hint].filter(Boolean).join(' ')).includes(qNorm))
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
        ? (hasQuery ? 'Проекты не найдены.' : 'Нет проектов.')
        : undefined

    if (!activeProject && showProjectsSection) {
      push('projects', 'Projects', projectItems, projectsNote)
    }

    const groupOrder: CmdGroup[] = ['Project', 'Graph', 'UI', 'Selection', 'Navigation']
    for (const g of groupOrder) {
      const items = filteredCommands.filter((c) => c.group === g)
      push(`actions.${g}`, `Actions: ${g}`, items)
    }

    if (activeProject && showProjectsSection) {
      push('projects', 'Projects', projectItems, projectsNote)
    }

    const wantsFiles = q.length >= 2
    const fileNote =
      !activeProject && wantsFiles
        ? 'Выбери проект, чтобы искать файлы.'
        : activeProject && wantsFiles && filesBusy
          ? 'Поиск файлов…'
          : activeProject && wantsFiles && !filesBusy && fileItems.length === 0
            ? 'Файлы не найдены.'
            : undefined

    if (wantsFiles || fileItems.length > 0) {
      push('files', 'Files', fileItems, fileNote)
    }

    return out
  }, [activeProject, fileItems, filesBusy, filteredCommands, projectItems, qRaw])

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
        ? [item.title, item.subtitle || '', 'Enter — открыть', 'Shift+Enter — открыть + toggle pin'].filter(Boolean).join('\n')
        : [item.title, item.subtitle || '', item.hint ? `Keys: ${item.hint}` : ''].filter(Boolean).join('\n')
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
        <div className="flex items-start justify-between gap-3">
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
      ? (hasQuery ? 'Выбери проект, чтобы стали доступны команды и поиск файлов.' : 'Выбери проект в секции Projects.')
      : (!hasQuery
          ? 'Начни ввод, чтобы переключить проект или найти файл.'
          : (qTrim.length < 2 ? 'Файлы: введи минимум 2 символа для поиска.' : null))

  return (
    <Modal open={open} title="Command palette" onClose={onClose}>
      <div>
        <div className="flex items-center gap-2">
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Команда, проект или путь файла…"
            className={['flex-1', controlClass].join(' ')}
            title="Поиск по командам/проектам/файлам. Файлы ищутся по активному проекту (минимум 2 символа)."
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
            <div className="text-xs text-neutral-500">Ничего не найдено.</div>
          )}
        </div>

        <div className="mt-4 text-[11px] text-neutral-500 flex flex-wrap gap-x-3 gap-y-1">
          <span>
            <span className="text-neutral-300">Enter</span> — открыть/выполнить
          </span>
          <span>
            <span className="text-neutral-300">Esc</span> — закрыть
          </span>
          <span>
            <span className="text-neutral-300">↑/↓</span> — навигация
          </span>
          <span>
            <span className="text-neutral-300">Ctrl/⌘+K</span> — открыть
          </span>
          <span>
            <span className="text-neutral-300">Shift+Enter</span> — toggle pin (file)
          </span>
          <span>
            <span className="text-neutral-300">Ctrl/⌘+Shift+M</span> — compact
          </span>
        </div>

        <Modal open={helpOpen} title="Подсказка: Command palette" onClose={() => setHelpOpen(false)}>
          <div className="space-y-2">
            <div className="text-neutral-200 font-semibold">
              Что это
            </div>
            <div>
              • Command palette — быстрый доступ к действиям (Actions), переключению проектов и поиску файлов.
            </div>
            <div className="pt-2 text-neutral-200 font-semibold">
              Поиск
            </div>
            <div>
              • Actions/Projects фильтруются локально по вводу.
            </div>
            <div>
              • Files ищутся через backend по активному проекту (<span className="font-mono">min 2 chars</span>).
            </div>
            <div className="text-neutral-400 text-[12px]">
              Совет: для файлов используйте подстроку пути, например <span className="font-mono">service/</span> или имя модуля.
            </div>

            <div className="pt-2 text-neutral-200 font-semibold">
              Управление
            </div>
            <div>
              • <span className="font-mono">Enter</span> — выполнить действие / выбрать проект / открыть файл.
            </div>
            <div>
              • <span className="font-mono">Shift+Enter</span> на файле — открыть и <span className="font-mono">toggle</span> pin (закрепить/открепить).
            </div>
            <div>
              • <span className="font-mono">↑/↓</span> — перемещение по списку.
            </div>
            <div>
              • <span className="font-mono">Esc</span> — закрыть.
            </div>
            <div className="pt-2 text-neutral-200 font-semibold">
              Группы
            </div>
            <div>
              • Actions сгруппированы по доменам: Project / Graph / UI / Selection / Navigation.
            </div>
            <div>
              • Projects — список проектов. Появляется при вводе запроса; если проект не выбран — показывается сразу.
              Чтобы переключить проект при пустом запросе — просто начни ввод.
            </div>
            <div>
              • Files — результаты поиска файлов. Появляется при вводе 2+ символов; поиск идёт в активном проекте.
              Если проекта нет — сначала выбери проект.
            </div>
          </div>
        </Modal>
      </div>
    </Modal>
  )
}
