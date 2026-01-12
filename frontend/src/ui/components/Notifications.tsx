// frontend/src/ui/components/Notifications.tsx
import React from 'react'
import clsx from 'clsx'
import type { NotificationItem } from '../useCGRAPHApp'

type Props = {
  notifications: NotificationItem[]
  onDismiss: (id: string) => void
}

export function Notifications({ notifications, onDismiss }: Props) {
  if (!notifications.length) return null

  return (
    <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 w-80">
      {notifications.map((n) => (
        <div
          key={n.id}
          className={clsx(
            'rounded-md border px-3 py-2 shadow-lg text-sm flex justify-between gap-3 items-start',
            n.kind === 'error'
              ? 'bg-red-950/80 border-red-800 text-red-100'
              : n.kind === 'info'
                ? 'bg-neutral-900/80 border-neutral-700 text-neutral-100'
                : 'bg-neutral-900/80 border-neutral-700 text-neutral-100'
          )}
        >
          <div className="flex-1 whitespace-pre-wrap leading-relaxed break-words">
            {n.text}
          </div>
          <button
            className="text-xs text-neutral-300 hover:text-white"
            onClick={() => onDismiss(n.id)}
            aria-label="Закрыть уведомление"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  )
}
