// frontend/src/api/orgs.ts
// API helpers for org endpoints: listOrgs/getOrg/createOrg.
import { api } from '@/shared/api/client'
import type { Org } from '@/shared/types'

export async function listOrgs(): Promise<Org[]> {
  const r = await api.get('/orgs')
  return r.data
}

export async function getOrg(orgId: number): Promise<Org> {
  const r = await api.get(`/orgs/${orgId}`)
  return r.data
}

export async function createOrg(name: string): Promise<Org> {
  const r = await api.post('/orgs', { name })
  return r.data
}
