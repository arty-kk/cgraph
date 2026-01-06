// frontend/src/lib/errors.ts
export function extractError(e: any): string {
    const detail = e?.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (detail != null) {
      try {
        return JSON.stringify(detail, null, 2)
      } catch {
        return String(detail)
      }
    }
    if (typeof e?.message === 'string') return e.message
    return String(e)
  }
  