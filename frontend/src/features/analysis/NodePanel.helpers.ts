export const isRecord = (val: unknown): val is Record<string, unknown> => typeof val === 'object' && val !== null

export const clampFloat = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

export const fmtK = (n: unknown): string => {
  const v = Number(n)
  if (!Number.isFinite(v)) return '—'
  const abs = Math.abs(v)
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`
  if (abs >= 1_000) return `${Math.round(v / 1_000)}k`
  return String(Math.round(v))
}

export const fmtDuration = (n: unknown): string => {
  const v = Number(n)
  if (!Number.isFinite(v)) return '—'
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(2)}s`
  return `${Math.round(v)}ms`
}

export const fmtTraceArgs = (args: unknown): string => {
  if (args == null) return '—'
  let raw = ''
  if (typeof args === 'string') {
    raw = args
  } else {
    try {
      raw = JSON.stringify(args)
    } catch {
      raw = String(args)
    }
  }
  if (!raw) return '—'
  const maxLen = 240
  return raw.length > maxLen ? `${raw.slice(0, maxLen)}…` : raw
}

export const quoteShell = (value: unknown): string => {
  const raw = String(value ?? '').trim()
  if (!raw) return "''"
  return `'${raw.replace(/'/g, "'\\''")}'`
}

export const formatTraceCommand = (entry: Record<string, unknown>): string => {
  const name = String(entry.name ?? '')
  const args = isRecord(entry.args) ? entry.args : {}

  if (name === 'search_paths') {
    const query = String(args.query ?? '').trim()
    return query ? `rg --files | rg ${quoteShell(query)}` : 'rg --files'
  }
  if (name === 'search_tests') {
    const query = String(args.query ?? '').trim()
    const base = "rg --files | rg 'test|tests|spec'"
    return query ? `${base} | rg ${quoteShell(query)}` : base
  }
  if (name === 'search_text') {
    const query = String(args.query ?? '').trim()
    const paths = Array.isArray(args.paths)
      ? args.paths.filter((p): p is string => typeof p === 'string').map((p) => quoteShell(p))
      : []
    if (query && paths.length > 0) return `rg -n ${quoteShell(query)} ${paths.join(' ')}`
    if (query) return `rg -n ${quoteShell(query)}`
    return 'rg -n <pattern>'
  }
  if (name === 'get_file_lines') {
    const path = String(args.path ?? '').trim()
    const start = Number(args.start_line)
    const end = Number(args.end_line)
    if (path && Number.isFinite(start) && Number.isFinite(end)) {
      return `sed -n '${start},${end}p' ${quoteShell(path)}`
    }
    return 'sed -n <start>,<end>p <path>'
  }
  if (name === 'get_file') {
    const path = String(args.path ?? '').trim()
    return path ? `cat ${quoteShell(path)}` : 'cat <path>'
  }

  return name || 'tool'
}

export const asStringList = (value: unknown): string[] => {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => (typeof item === 'string' ? item.trim() : ''))
    .filter(Boolean)
}

