//frontend/src/ui/components/Modal.tsx
import React, { useEffect, useRef } from 'react'

type ModalStackItem = { id: number }

let modalIdSeq = 0
const modalStack: ModalStackItem[] = []
let savedBodyOverflow: string | null = null

function syncGlobalModalState() {
  if (typeof document === 'undefined') return
  try {
    const count = modalStack.length
    document.body.dataset.csModalOpenCount = String(count)

    if (count > 0) {
      if (savedBodyOverflow == null) savedBodyOverflow = document.body.style.overflow
      document.body.style.overflow = 'hidden'
    } else {
      if (savedBodyOverflow != null) {
        document.body.style.overflow = savedBodyOverflow
        savedBodyOverflow = null
      } else {
        document.body.style.overflow = ''
      }
    }
  } catch {
    // ignore
  }
}

function pushModal(id: number) {
  if (modalStack.some((m) => m.id === id)) return
  modalStack.push({ id })
  syncGlobalModalState()
}

function removeModal(id: number) {
  const idx = modalStack.findIndex((m) => m.id === id)
  if (idx >= 0) modalStack.splice(idx, 1)
  syncGlobalModalState()
}

function isTopModal(id: number): boolean {
  const top = modalStack[modalStack.length - 1]
  return !!top && top.id === id
}

type Props = {
  open: boolean
  title: string
  onClose: () => void
  children: React.ReactNode
}

export function Modal({ open, title, onClose, children }: Props) {
  const idRef = useRef<number>(0)
  if (idRef.current === 0) idRef.current = ++modalIdSeq

  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!open) return
    const id = idRef.current
    pushModal(id)
    return () => removeModal(id)
  }, [open])

  useEffect(() => {
    if (!open) return
    const id = idRef.current
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (!isTopModal(id)) return
      e.preventDefault()
      onCloseRef.current()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open])

  if (!open) return null

  const titleId = `cs-modal-title-${idRef.current}`

  return (
    <div data-cs-modal="1" className="fixed inset-0 z-[100] flex items-center justify-center" onMouseDown={onClose}>
      <div className="absolute inset-0 bg-black/60" />

      <div
        className="relative w-[min(720px,calc(100vw-32px))] max-h-[calc(100vh-32px)] overflow-auto rounded-md bg-neutral-950 border border-neutral-800 shadow-xl p-4"
        onMouseDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <div className="flex items-start justify-between gap-3">
          <div id={titleId} className="text-sm font-semibold text-neutral-100">
            {title}
          </div>
          <button
            className="text-neutral-400 hover:text-neutral-100"
            onClick={onClose}
            aria-label="Закрыть"
            type="button"
          >
            ×
          </button>
        </div>
        <div className="mt-3 text-sm text-neutral-200 leading-relaxed">{children}</div>
      </div>
    </div>
  )
}
