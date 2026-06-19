import { useCallback, useEffect, useRef, useState } from 'react'
import { getTaskStatus, isTaskStatus, type TaskStatus } from '@/api'
import type { TaskBannerItem } from '../internal'

export function useTaskTracking() {
  const [taskStatuses, setTaskStatuses] = useState<TaskBannerItem[]>([])
  const taskStatusesRef = useRef<TaskBannerItem[]>([])
  useEffect(() => {
    taskStatusesRef.current = taskStatuses
  }, [taskStatuses])

  const trackTaskStatus = useCallback((task: TaskStatus, kind: TaskBannerItem['kind'], label: string) => {
    setTaskStatuses((prev) => {
      const existing = prev.find((item) => item.id === task.task_id)
      if (existing) {
        return prev.map((item) =>
          item.id === task.task_id
            ? { ...item, status: task.status, error: task.error ? String(task.error) : item.error }
            : item
        )
      }
      const next: TaskBannerItem = {
        id: task.task_id,
        kind,
        status: task.status,
        label,
        startedAt: Date.now(),
        finishedAt: null,
        error: task.error ? String(task.error) : null,
      }
      return [...prev, next].slice(-5)
    })
  }, [])

  const refreshTaskStatuses = useCallback(async () => {
    const pending = taskStatusesRef.current.filter((item) => item.status === 'pending' || item.status === 'running')
    if (!pending.length) return
    const updates = await Promise.all(
      pending.map(async (item) => {
        try {
          const status = await getTaskStatus(item.id)
          return { item, status }
        } catch {
          return { item, status: null }
        }
      })
    )
    setTaskStatuses((prev) =>
      prev.map((item) => {
        const update = updates.find((u) => u.item.id === item.id)
        if (!update || !update.status) return item
        const finishedAt =
          update.status.status === 'succeeded' || update.status.status === 'failed'
            ? Date.now()
            : item.finishedAt
        return {
          ...item,
          status: update.status.status,
          error: update.status.error ? String(update.status.error) : item.error,
          finishedAt,
        }
      })
    )
  }, [])

  useEffect(() => {
    if (!taskStatuses.length) return
    const interval = window.setInterval(() => {
      void refreshTaskStatuses()
    }, 3000)
    return () => window.clearInterval(interval)
  }, [refreshTaskStatuses, taskStatuses.length])

  const clearFinishedTasks = useCallback(() => {
    setTaskStatuses((prev) => prev.filter((item) => item.status === 'pending' || item.status === 'running'))
  }, [])

  const dismissTaskStatus = useCallback((taskId: string) => {
    setTaskStatuses((prev) => prev.filter((item) => item.id !== taskId))
  }, [])

  return { taskStatuses, trackTaskStatus, refreshTaskStatuses, clearFinishedTasks, dismissTaskStatus }
}
