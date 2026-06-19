import { useEffect } from 'react'
import type { Org } from '@/api'
import { safeStorageGet } from '@/shared/lib/storage'

type Params = {
  orgs: Org[]
  selectedOrgId: number | null
  applyOrgSelection: (orgId: number | null) => void
  orgStorageKey: string
}

/** Auto-selects an org from storage / single-org / clears, when the org list or selection changes. Extracted verbatim. */
export function useOrgAutoSelect({ orgs, selectedOrgId, applyOrgSelection, orgStorageKey }: Params) {
  useEffect(() => {
    if (orgs.length === 0) {
      if (selectedOrgId !== null) applyOrgSelection(null)
      return
    }

    if (selectedOrgId !== null && orgs.some((org) => org.id === selectedOrgId)) return

    let storedId: number | null = null
    const raw = safeStorageGet(orgStorageKey)
    const n = Number(raw)
    if (Number.isFinite(n)) storedId = Math.trunc(n)

    if (storedId !== null && orgs.some((org) => org.id === storedId)) {
      applyOrgSelection(storedId)
      return
    }

    if (orgs.length === 1) {
      applyOrgSelection(orgs[0].id)
      return
    }

    applyOrgSelection(null)
  }, [applyOrgSelection, orgs, selectedOrgId])
}
