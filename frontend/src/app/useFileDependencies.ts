import { useCallback, useEffect, useState } from 'react'
import { getFileDependencies, type Project } from '@/api'
import type { DependencyMeta } from './useStubGraphApp.internal'

type Params = {
  activeProject: Project | null
  activeFilePath: string | null
}

/** File inbound/outbound dependency loading + pagination. Extracted verbatim from useStubGraphApp. */
export function useFileDependencies({ activeProject, activeFilePath }: Params) {
  const [fileDependencies, setFileDependencies] = useState<{ in: string[]; out: string[] } | null>(null)
  const [fileDependenciesMeta, setFileDependenciesMeta] = useState<DependencyMeta | null>(null)
  const [fileDependenciesBusy, setFileDependenciesBusy] = useState(false)

  useEffect(() => {
    if (!activeProject || !activeFilePath) {
      setFileDependencies(null)
      setFileDependenciesMeta(null)
      setFileDependenciesBusy(false)
      return
    }
    let active = true
    setFileDependenciesBusy(true)
    getFileDependencies(activeProject.id, activeFilePath, { limit: 2000 })
      .then((res) => {
        if (!active) return
        setFileDependencies({ in: res.inbound || [], out: res.outbound || [] })
        setFileDependenciesMeta({
          total_in: res.meta?.total_inbound ?? res.inbound?.length ?? 0,
          total_out: res.meta?.total_outbound ?? res.outbound?.length ?? 0,
          truncated_in: Boolean(res.meta?.truncated_inbound),
          truncated_out: Boolean(res.meta?.truncated_outbound),
          next_cursor_in: res.meta?.next_cursor_in ?? null,
          next_cursor_out: res.meta?.next_cursor_out ?? null,
          cursor_in: res.meta?.cursor_in ?? null,
          cursor_out: res.meta?.cursor_out ?? null,
        })
      })
      .catch(() => {
        if (!active) return
        setFileDependencies({ in: [], out: [] })
        setFileDependenciesMeta({
          total_in: 0,
          total_out: 0,
          truncated_in: false,
          truncated_out: false,
          next_cursor_in: null,
          next_cursor_out: null,
          cursor_in: null,
          cursor_out: null,
        })
      })
      .finally(() => {
        if (active) setFileDependenciesBusy(false)
      })
    return () => {
      active = false
    }
  }, [activeFilePath, activeProject])

  const loadMoreDependencies = useCallback(async () => {
    if (!activeProject || !activeFilePath || !fileDependenciesMeta) return
    if (!fileDependenciesMeta.next_cursor_in && !fileDependenciesMeta.next_cursor_out) return
    setFileDependenciesBusy(true)
    try {
      const res = await getFileDependencies(activeProject.id, activeFilePath, {
        limit: 2000,
        cursorIn: fileDependenciesMeta.next_cursor_in ?? undefined,
        cursorOut: fileDependenciesMeta.next_cursor_out ?? undefined,
      })
      setFileDependencies((prev) => {
        const prevIn = prev?.in ?? []
        const prevOut = prev?.out ?? []
        const nextIn = [...prevIn, ...(res.inbound || [])]
        const nextOut = [...prevOut, ...(res.outbound || [])]
        return {
          in: Array.from(new Set(nextIn)),
          out: Array.from(new Set(nextOut)),
        }
      })
      setFileDependenciesMeta({
        total_in: res.meta?.total_inbound ?? fileDependenciesMeta.total_in,
        total_out: res.meta?.total_outbound ?? fileDependenciesMeta.total_out,
        truncated_in: Boolean(res.meta?.truncated_inbound),
        truncated_out: Boolean(res.meta?.truncated_outbound),
        next_cursor_in: res.meta?.next_cursor_in ?? null,
        next_cursor_out: res.meta?.next_cursor_out ?? null,
        cursor_in: res.meta?.cursor_in ?? fileDependenciesMeta.cursor_in ?? null,
        cursor_out: res.meta?.cursor_out ?? fileDependenciesMeta.cursor_out ?? null,
      })
    } catch {
      // keep existing state on failure
    } finally {
      setFileDependenciesBusy(false)
    }
  }, [activeFilePath, activeProject, fileDependenciesMeta])

  return { fileDependencies, fileDependenciesMeta, fileDependenciesBusy, loadMoreDependencies }
}
