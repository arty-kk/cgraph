import { useCallback, useEffect, useState } from 'react'
import {
  getProjectDocs,
  buildProjectDocsStatus,
  isTaskStatus,
  waitForTaskResult,
  type ProjectDocs,
} from '@/api'
import { extractError, getAppErrorInfo } from '@/shared/lib/errors'
import { useNotifications } from './NotificationsContext'
import { useTaskTracking } from './TaskTrackingContext'
import { useWorkspace } from '../workspace'

/** Project documentation load/build state + actions. Extracted verbatim from useStubGraphApp. */
export function useDocs() {
  const { notifyInfo, setErrorMessage } = useNotifications()
  const { trackTaskStatus } = useTaskTracking()
  const { activeProject } = useWorkspace().state
  const [docs, setDocs] = useState<ProjectDocs | null>(null)
  const [docsBusy, setDocsBusy] = useState(false)
  const [docsBuildBusy, setDocsBuildBusy] = useState(false)
  const [docsBuildError, setDocsBuildError] = useState<string | null>(null)

  useEffect(() => {
    setDocs(null)
    setDocsBuildError(null)
  }, [activeProject?.id])

  const loadDocs = useCallback(async () => {
    if (!activeProject) return
    setDocsBusy(true)
    setDocsBuildError(null)
    setErrorMessage(null)
    try {
      const d = await getProjectDocs(activeProject.id)
      setDocs(d)
    } catch (e: any) {
      const info = getAppErrorInfo(e)
      const message = info?.message?.toLowerCase() ?? ''
      const isDocsMissing =
        info?.code === 'not_found' &&
        ((message.includes('документац') && message.includes('не найден')) ||
          (message.includes('docs') && (message.includes('not found') || message.includes('missing'))))
      if (isDocsMissing) {
        setDocs(null)
        return
      }
      setDocs(null)
      setErrorMessage(extractError(e))
    } finally {
      setDocsBusy(false)
    }
  }, [activeProject, setErrorMessage])

  const buildDocs = useCallback(async () => {
    if (!activeProject) return
    setDocsBuildBusy(true)
    setDocsBuildError(null)
    setErrorMessage(null)
    try {
      const initial = await buildProjectDocsStatus(activeProject.id)
      if (isTaskStatus(initial)) {
        trackTaskStatus(initial, 'docs', `Docs ${activeProject.name}`)
      }
      const d = await waitForTaskResult<ProjectDocs>(initial, { pollIntervalMs: 1200, maxAttempts: 300 })
      setDocs(d)
      setDocsBuildError(null)
      notifyInfo('Docs built')
    } catch (e: any) {
      setDocsBuildError(extractError(e))
      setErrorMessage(extractError(e))
    } finally {
      setDocsBuildBusy(false)
    }
  }, [activeProject, notifyInfo, setErrorMessage, trackTaskStatus])

  return { docs, docsBusy, docsBuildBusy, docsBuildError, loadDocs, buildDocs }
}
