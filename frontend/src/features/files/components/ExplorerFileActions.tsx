import React from 'react'
import type { Project } from '@/api'
import { Modal } from '@/shared/ui/Modal'

type Props = {
  activeProject: Project | null
  busy: boolean
  selectedPath: string | null
  onCreateFile: (path: string) => void | Promise<void>
  onRenameFile: (path: string, newPath: string) => void | Promise<void>
  onDeleteFile: (path: string) => void | Promise<void>
  onSelectPath: (path: string) => void | Promise<void>
  onOpenFileEditor?: (path: string) => void | Promise<void>
  compact?: boolean
}

/**
 * File CRUD controls for the explorer: Create / Rename / Delete buttons and
 * their confirm modals (with path validation). Extracted verbatim from
 * ExplorerTree; owns its own dialog state.
 */
export function ExplorerFileActions({
  activeProject,
  busy,
  selectedPath,
  onCreateFile,
  onRenameFile,
  onDeleteFile,
  onSelectPath,
  onOpenFileEditor,
  compact = false,
}: Props) {
  const labelRowClass = 'flex items-center gap-2 leading-none'
  const fieldLabelClass = 'text-[11px] font-semibold text-neutral-200'
  const inputSmClass = 'w-full h-9 rounded-md bg-neutral-900 border border-neutral-800 px-3 text-sm outline-none disabled:opacity-50'

  const selectedFilePath = String(selectedPath || '').trim()
  const actionsDisabled = busy || !activeProject
  const renameDisabled = actionsDisabled || !selectedFilePath
  const deleteDisabled = actionsDisabled || !selectedFilePath

  const [createOpen, setCreateOpen] = React.useState(false)
  const [renameOpen, setRenameOpen] = React.useState(false)
  const [deleteOpen, setDeleteOpen] = React.useState(false)
  const [createInput, setCreateInput] = React.useState('')
  const [renameInput, setRenameInput] = React.useState('')
  const [createError, setCreateError] = React.useState<string | null>(null)
  const [renameError, setRenameError] = React.useState<string | null>(null)
  const [createOpError, setCreateOpError] = React.useState<string | null>(null)
  const [renameOpError, setRenameOpError] = React.useState<string | null>(null)
  const [deleteOpError, setDeleteOpError] = React.useState<string | null>(null)
  const [openAfterCreate, setOpenAfterCreate] = React.useState(false)
  const [revealInEditor, setRevealInEditor] = React.useState(false)

  const validatePath = React.useCallback((input: string): string | null => {
    const raw = String(input ?? '')
    if (!raw.trim()) return 'Path is required.'
    if (raw !== raw.trim()) return 'Path must not include leading or trailing spaces.'
    if (raw.includes('..')) return 'Path must not contain ".." segments.'
    if (raw.startsWith('/') || /^[A-Za-z]:[\\/]/.test(raw)) return 'Path must be relative to the project root.'
    return null
  }, [])

  React.useEffect(() => {
    if (createOpen) {
      setCreateInput('')
      setCreateError(null)
      setCreateOpError(null)
      return
    }
    setCreateError(null)
    setCreateOpError(null)
  }, [createOpen])

  React.useEffect(() => {
    if (renameOpen) {
      setRenameInput(selectedFilePath)
      setRenameError(null)
      setRenameOpError(null)
      return
    }
    setRenameError(null)
    setRenameOpError(null)
  }, [renameOpen, selectedFilePath])

  React.useEffect(() => {
    if (deleteOpen) {
      setDeleteOpError(null)
      return
    }
    setDeleteOpError(null)
  }, [deleteOpen])

  const handleCreateSubmit = React.useCallback(async () => {
    if (actionsDisabled) return
    const err = validatePath(createInput)
    setCreateError(err)
    setCreateOpError(null)
    if (err) return
    const nextPath = createInput.trim()
    try {
      await Promise.resolve(onCreateFile(nextPath))
      if (revealInEditor) {
        await Promise.resolve(onSelectPath(nextPath))
      }
      if (openAfterCreate && onOpenFileEditor) {
        await Promise.resolve(onOpenFileEditor(nextPath))
      }
      setCreateOpen(false)
    } catch (e: any) {
      const message = e instanceof Error ? e.message : String(e)
      setCreateOpError(message || 'Failed to create file.')
    }
  }, [actionsDisabled, createInput, onCreateFile, onOpenFileEditor, onSelectPath, openAfterCreate, revealInEditor, validatePath])

  const handleRenameSubmit = React.useCallback(async () => {
    if (renameDisabled) return
    const err = validatePath(renameInput)
    setRenameError(err)
    setRenameOpError(null)
    if (err) return
    const nextPath = renameInput.trim()
    try {
      await Promise.resolve(onRenameFile(selectedFilePath, nextPath))
      if (revealInEditor) {
        await Promise.resolve(onSelectPath(nextPath))
      }
      setRenameOpen(false)
    } catch (e: any) {
      const message = e instanceof Error ? e.message : String(e)
      setRenameOpError(message || 'Failed to rename file.')
    }
  }, [onRenameFile, onSelectPath, renameDisabled, renameInput, revealInEditor, selectedFilePath, validatePath])

  const handleDeleteSubmit = React.useCallback(async () => {
    if (deleteDisabled) return
    setDeleteOpError(null)
    try {
      await Promise.resolve(onDeleteFile(selectedFilePath))
      setDeleteOpen(false)
    } catch (e: any) {
      const message = e instanceof Error ? e.message : String(e)
      setDeleteOpError(message || 'Failed to delete file.')
    }
  }, [deleteDisabled, onDeleteFile, selectedFilePath])

  return (
    <>
      {!compact && (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
            disabled={actionsDisabled}
            onClick={() => {
              if (actionsDisabled) return
              setCreateOpen(true)
            }}
            title="Create new file"
          >
            Create
          </button>
          <button
            type="button"
            className="rounded-md border border-neutral-800 bg-neutral-900 px-2 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
            disabled={renameDisabled}
            onClick={() => {
              if (renameDisabled) return
              setRenameOpen(true)
            }}
            title="Rename selected file"
          >
            Rename
          </button>
          <button
            type="button"
            className="rounded-md border border-rose-900/70 bg-rose-950/40 px-2 py-1 text-[11px] font-semibold text-rose-100 hover:bg-rose-900/40 disabled:opacity-50"
            disabled={deleteDisabled}
            onClick={() => {
              if (deleteDisabled) return
              setDeleteOpen(true)
            }}
            title="Delete selected file"
          >
            Delete
          </button>
        </div>
      )}

      <Modal
        open={createOpen}
        title="Create file"
        onClose={() => setCreateOpen(false)}
        panelClassName="w-[min(520px,calc(100vw-32px))]"
      >
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            void handleCreateSubmit()
          }}
        >
          <label className="text-xs text-neutral-300">
            <div className={labelRowClass}>
              <span className={fieldLabelClass}>Path</span>
            </div>
            <input
              className={inputSmClass + ' mt-1'}
              value={createInput}
              onChange={(e) => {
                setCreateInput(e.target.value)
                setCreateError(null)
                setCreateOpError(null)
              }}
              placeholder="relative/path/to/file.ts"
              disabled={actionsDisabled}
              autoFocus
            />
          </label>
          {createError && (
            <div className="text-[11px] text-rose-300">{createError}</div>
          )}
          {createOpError && (
            <div className="text-[11px] text-rose-300">{createOpError}</div>
          )}
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-[11px] text-neutral-300">
              <input
                type="checkbox"
                className="accent-indigo-500"
                checked={openAfterCreate}
                onChange={(e) => setOpenAfterCreate(e.target.checked)}
              />
              Open after create
            </label>
            <label className="flex items-center gap-2 text-[11px] text-neutral-300">
              <input
                type="checkbox"
                className="accent-indigo-500"
                checked={revealInEditor}
                onChange={(e) => setRevealInEditor(e.target.checked)}
              />
              Reveal in editor
            </label>
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800"
              onClick={() => setCreateOpen(false)}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
              disabled={actionsDisabled}
            >
              Create
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        open={renameOpen}
        title="Rename file"
        onClose={() => setRenameOpen(false)}
        panelClassName="w-[min(520px,calc(100vw-32px))]"
      >
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault()
            void handleRenameSubmit()
          }}
        >
          <label className="text-xs text-neutral-300">
            <div className={labelRowClass}>
              <span className={fieldLabelClass}>New path</span>
            </div>
            <input
              className={inputSmClass + ' mt-1'}
              value={renameInput}
              onChange={(e) => {
                setRenameInput(e.target.value)
                setRenameError(null)
                setRenameOpError(null)
              }}
              placeholder={selectedFilePath}
              disabled={renameDisabled}
              autoFocus
            />
          </label>
          {renameError && (
            <div className="text-[11px] text-rose-300">{renameError}</div>
          )}
          {renameOpError && (
            <div className="text-[11px] text-rose-300">{renameOpError}</div>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800"
              onClick={() => setRenameOpen(false)}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800 disabled:opacity-50"
              disabled={renameDisabled}
            >
              Rename
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        open={deleteOpen}
        title="Delete file"
        onClose={() => setDeleteOpen(false)}
        panelClassName="w-[min(520px,calc(100vw-32px))]"
      >
        <div className="space-y-3">
          <div className="text-sm text-neutral-200">
            Delete file "{selectedFilePath}"? This action cannot be undone.
          </div>
          {deleteOpError && (
            <div className="text-[11px] text-rose-300">{deleteOpError}</div>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              className="rounded-md border border-neutral-800 bg-neutral-900 px-3 py-1 text-[11px] font-semibold text-neutral-200 hover:bg-neutral-800"
              onClick={() => setDeleteOpen(false)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="rounded-md border border-rose-900/70 bg-rose-950/40 px-3 py-1 text-[11px] font-semibold text-rose-100 hover:bg-rose-900/40 disabled:opacity-50"
              onClick={() => void handleDeleteSubmit()}
              disabled={deleteDisabled}
            >
              Yes
            </button>
          </div>
        </div>
      </Modal>
    </>
  )
}
