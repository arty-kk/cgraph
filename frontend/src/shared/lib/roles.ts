// frontend/src/lib/roles.ts
// Mirror of the backend role hierarchy (backend/app/rbac.py) so UI affordances
// stay aligned with server-side authorization. The backend remains the
// enforcement point; this only gates what the UI offers.
export const ROLE_ORDER: Record<string, number> = {
  viewer: 0,
  member: 1,
  admin: 2,
  owner: 3,
}

export function roleAtLeast(role: string | null | undefined, required: string): boolean {
  if (role == null) return false
  const have = ROLE_ORDER[role]
  const need = ROLE_ORDER[required]
  if (have == null || need == null) return false
  return have >= need
}
