// frontend/src/lib/errors.ts
type AnyRecord = Record<string, any>

function safeJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function extractError(e: unknown): string {
  const resp = (e as any)?.response
  const data = resp?.data

  if (typeof data === 'string' && data.trim()) return data

  const appError = (data as AnyRecord | undefined)?.error
  if (appError && typeof appError === 'object') {
    const code =
      typeof (appError as AnyRecord).code === 'string' ? String((appError as AnyRecord).code).trim() : ''
    const message =
      typeof (appError as AnyRecord).message === 'string'
        ? String((appError as AnyRecord).message).trim()
        : ''
    const context = (appError as AnyRecord).context

    const header = `${code ? `[${code}] ` : ''}${message}`.trim()
    if (context != null && typeof context === 'object') {
      const ctxText = safeJson(context)
      return header ? `${header}\n${ctxText}` : ctxText
    }
    if (header) return header
  }

  const detail = (data as AnyRecord | undefined)?.detail
  if (typeof detail === 'string') return detail
  if (detail != null) return safeJson(detail)
    
  if (typeof (e as any)?.message === 'string') return (e as any).message

  return String(e)
}
  
