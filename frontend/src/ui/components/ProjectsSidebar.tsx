// frontend/src/ui/components/ProjectsSidebar.tsx
import React from 'react'
import clsx from 'clsx'
import type { Project } from '../../api'
import { clampInt } from '../../lib/number'

type Props = {
  projects: Project[]
  activeProject: Project | null
  newName: string
  newPath: string
  busy: boolean
  error: string | null

  setNewName: (v: string) => void
  setNewPath: (v: string) => void

  // graph controls
  graphMode: 'auto' | 'full' | 'limit'
  graphLimitN: number
  setGraphMode: (v: 'auto' | 'full' | 'limit') => void
  setGraphLimitN: (v: number) => void

  onPickProject: (p: Project) => void | Promise<void>
  onCreateProject: () => void | Promise<void>
  onScan: () => void | Promise<void>
  onRefresh: () => void | Promise<void>
}

export function ProjectsSidebar({
  projects,
  activeProject,
  newName,
  newPath,
  busy,
  error,
  setNewName,
  setNewPath,
  graphMode,
  graphLimitN,
  setGraphMode,
  setGraphLimitN,
  onPickProject,
  onCreateProject,
  onScan,
  onRefresh,
}: Props) {
  return (
    <div className="border-r border-neutral-800 p-4 flex flex-col gap-3">
      <div className="text-lg font-semibold">Code Surgeon</div>

      <div className="text-sm text-neutral-300">
        Локальный граф + LLM-операции. Бэк: <span className="font-mono">:8000</span>
      </div>

      <div className="mt-2 text-sm font-semibold text-neutral-200">Проекты</div>
      <div className="flex flex-col gap-2">
        {projects.map((p) => (
          <button
            key={p.id}
            className={clsx(
              'text-left rounded-md px-3 py-2 border',
              activeProject?.id === p.id
                ? 'bg-neutral-900 border-neutral-700'
                : 'bg-neutral-950 border-neutral-800 hover:border-neutral-700'
            )}
            onClick={() => onPickProject(p)}
            disabled={busy}
          >
            <div className="text-sm font-medium">{p.name}</div>
            <div className="text-xs text-neutral-400 truncate">{p.root_path}</div>
          </button>
        ))}
      </div>

      <div className="mt-3 text-sm font-semibold text-neutral-200">Добавить</div>
      <input
        className="w-full rounded-md bg-neutral-900 border border-neutral-800 px-3 py-2 text-sm"
        placeholder="name"
        value={newName}
        onChange={(e) => setNewName(e.target.value)}
      />
      <input
        className="w-full rounded-md bg-neutral-900 border border-neutral-800 px-3 py-2 text-sm"
        placeholder="/absolute/path/to/repo"
        value={newPath}
        onChange={(e) => setNewPath(e.target.value)}
      />
      <button
        className="rounded-md bg-indigo-600 hover:bg-indigo-500 px-3 py-2 text-sm font-semibold disabled:opacity-50"
        onClick={() => onCreateProject()}
        disabled={!newName.trim() || !newPath.trim() || busy}
      >
        Create project
      </button>

      <div className="mt-4 text-sm font-semibold text-neutral-200">Граф</div>
      <div className="grid grid-cols-2 gap-2">
        <label className="text-xs text-neutral-300">
          Mode
          <select
            className="mt-1 w-full rounded-md bg-neutral-900 border border-neutral-800 px-2 py-1 text-xs"
            value={graphMode}
            onChange={(e) => setGraphMode(e.target.value as any)}
            disabled={busy || !activeProject}
          >
            <option value="auto">auto</option>
            <option value="full">full</option>
            <option value="limit">top-N</option>
          </select>
        </label>

        <label className="text-xs text-neutral-300">
          N
          <input
            type="number"
            className="mt-1 w-full rounded-md bg-neutral-900 border border-neutral-800 px-2 py-1 text-xs"
            value={graphLimitN}
            min={100}
            max={20000}
            step={100}
            disabled={busy || !activeProject || graphMode !== 'limit'}
            onChange={(e) => {
              const raw = e.target.value
              const next = raw === '' ? 2000 : clampInt(Number(raw), 100, 20000)
              setGraphLimitN(next)
            }}
          />
        </label>
      </div>

      <div className="mt-2 flex gap-2">
        <button
          className="rounded-md bg-neutral-800 hover:bg-neutral-700 px-3 py-2 text-sm font-semibold disabled:opacity-50"
          onClick={() => onScan()}
          disabled={!activeProject || busy}
        >
          Scan
        </button>
        <button
          className="rounded-md bg-neutral-900 hover:bg-neutral-800 px-3 py-2 text-sm font-semibold disabled:opacity-50"
          onClick={() => onRefresh()}
          disabled={!activeProject || busy}
        >
          Refresh
        </button>
      </div>

      {error && <div className="mt-2 text-xs text-red-300 whitespace-pre-wrap">{error}</div>}

      <div className="mt-auto text-xs text-neutral-500 leading-relaxed">
        Docs:
        <ul className="list-disc ml-4 mt-1">
          <li>Responses API: platform.openai.com/docs/api-reference/responses</li>
          <li>Conversation state: platform.openai.com/docs/guides/conversation-state</li>
          <li>Prompt caching: platform.openai.com/docs/guides/prompt-caching</li>
        </ul>
      </div>
    </div>
  )
}
