// frontend/src/lib/errors.ts
type AnyRecord = Record<string, any>

export type AppErrorInfo = {
  code?: string
  message?: string
  context?: Record<string, unknown>
}

export type SemanticSearchErrorReason = 'embeddings_disabled' | 'missing_api_key'

const SEMANTIC_ERROR_MESSAGES: Record<SemanticSearchErrorReason, string> = {
  embeddings_disabled: 'Embeddings are disabled in settings.',
  missing_api_key: 'OPENAI_API_KEY is not configured.',
}

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

export function getAppErrorInfo(e: unknown): AppErrorInfo | null {
  const resp = (e as any)?.response
  const data = resp?.data
  const appError = (data as AnyRecord | undefined)?.error

  if (!appError || typeof appError !== 'object') return null

  const code = typeof (appError as AnyRecord).code === 'string' ? (appError as AnyRecord).code : undefined
  const message = typeof (appError as AnyRecord).message === 'string' ? (appError as AnyRecord).message : undefined
  const context = (appError as AnyRecord).context
  const contextRecord = context && typeof context === 'object' ? (context as Record<string, unknown>) : undefined

  return {
    code: code?.trim() || undefined,
    message: message?.trim() || undefined,
    context: contextRecord,
  }
}

export function getSemanticSearchErrorReason(e: unknown): SemanticSearchErrorReason | null {
  const info = getAppErrorInfo(e)
  if (!info) return null

  if (info.code === 'embeddings_disabled' || info.code === 'missing_api_key') return info.code
  if (!info.message) return null

  if (info.message === SEMANTIC_ERROR_MESSAGES.embeddings_disabled) return 'embeddings_disabled'
  if (info.message === SEMANTIC_ERROR_MESSAGES.missing_api_key) return 'missing_api_key'

  return null
}
  
