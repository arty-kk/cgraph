import { useCallback, useEffect, useRef, useState } from 'react'
import type { NotificationItem, NotificationKind } from './useStubGraphApp.internal'

/**
 * Owns the transient error string and the toast notification queue (with
 * auto-dismiss timers). Exposes notifyInfo / setErrorMessage / notifyError
 * used throughout the app. Extracted verbatim from useStubGraphApp.
 */
export function useNotifications() {
  const [error, setError] = useState<string | null>(null)
  const [notifications, setNotifications] = useState<NotificationItem[]>([])

  const notificationTimersRef = useRef<Record<string, number>>({})

  const clearNotificationTimer = useCallback((id: string) => {
    const t = notificationTimersRef.current[id]
    if (t != null) window.clearTimeout(t)
    delete notificationTimersRef.current[id]
  }, [])

  const dismissNotification = useCallback(
    (id: string) => {
      clearNotificationTimer(id)
      setNotifications((prev) => prev.filter((n) => n.id !== id))
    },
    [clearNotificationTimer],
  )

  useEffect(() => {
    return () => {
      Object.values(notificationTimersRef.current).forEach((t) => window.clearTimeout(t))
      notificationTimersRef.current = {}
    }
  }, [])

  const pushNotification = useCallback(
    (kind: NotificationKind, message: string) => {
      const text = message.trim()
      if (!text) return
      const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`
      const ttlMs = kind === 'error' ? 15_000 : 8_000

      setNotifications((prev) => {
        const next = [...prev.slice(-4), { id, kind, text }]
        const nextIds = new Set(next.map((n) => n.id))
        prev.forEach((n) => {
          if (!nextIds.has(n.id)) clearNotificationTimer(n.id)
        })
        return next
      })

      clearNotificationTimer(id)
      notificationTimersRef.current[id] = window.setTimeout(() => dismissNotification(id), ttlMs)
    },
    [clearNotificationTimer, dismissNotification]
  )

  const notifyError = useCallback((message: string) => {
    setError(message)
    pushNotification('error', message)
  }, [pushNotification])

  const setErrorMessage = useCallback(
    (message: string | null) => {
      if (message) {
        notifyError(message)
        return
      }
      setError(null)
    },
    [notifyError]
  )

  const notifyInfo = useCallback((message: string) => {
    pushNotification('info', message)
  }, [pushNotification])

  return {
    error,
    notifications,
    dismissNotification,
    pushNotification,
    notifyError,
    setErrorMessage,
    notifyInfo,
  }
}
