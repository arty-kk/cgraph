import { useCallback, useEffect, useState } from 'react'
import type { Project, ProjectFileItem, ProjectTreeEntry } from '@/api'

/** Per-path file metadata registry (cleared on project change). Extracted verbatim from useStubGraphApp. */
export function useFileMeta({ activeProject }: { activeProject: Project | null }) {
  const [fileMetaByPath, setFileMetaByPath] = useState<Record<string, ProjectFileItem>>({})

  const registerFileMeta = useCallback((entries: ProjectTreeEntry[]) => {
    setFileMetaByPath((prev) => {
      let changed = false
      const next = { ...prev }
      for (const entry of entries) {
        if (entry.type !== 'file' || !entry.file) continue
        if (next[entry.file.path] === entry.file) continue
        next[entry.file.path] = entry.file
        changed = true
      }
      return changed ? next : prev
    })
  }, [])

  useEffect(() => {
    setFileMetaByPath({})
  }, [activeProject?.id])

  return { fileMetaByPath, registerFileMeta }
}
