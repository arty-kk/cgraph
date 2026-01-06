// frontend/src/api/utils.ts
export function encodePath(path: string): string {
  const s = String(path ?? '')
  const normalized = s.replace(/\\/g, '/').replace(/\/+/g, '/')
  const trimmed = normalized.replace(/^\/+/, '').replace(/\/+$/, '')
  if (!trimmed) return ''
  return trimmed
    .split('/')
    .map(encodeURIComponent)
    .join('/')
}
  