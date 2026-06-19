import { describe, expect, it } from 'vitest'

import {
  asStringList,
  clampFloat,
  fmtDuration,
  fmtK,
  fmtTraceArgs,
  formatTraceCommand,
  isRecord,
  quoteShell,
} from './NodePanel.helpers'

describe('isRecord', () => {
  it('accepts plain objects', () => {
    expect(isRecord({})).toBe(true)
    expect(isRecord({ a: 1 })).toBe(true)
  })

  it('rejects null and primitives', () => {
    expect(isRecord(null)).toBe(false)
    expect(isRecord(undefined)).toBe(false)
    expect(isRecord('x')).toBe(false)
    expect(isRecord(42)).toBe(false)
  })

  it('treats arrays as records (typeof "object", not null)', () => {
    // Documents the implementation: the guard only checks typeof/null,
    // so arrays narrow to Record<string, unknown> too.
    expect(isRecord([])).toBe(true)
  })
})

describe('clampFloat', () => {
  it('clamps to the inclusive [lo, hi] range', () => {
    expect(clampFloat(5, 0, 10)).toBe(5)
    expect(clampFloat(-3, 0, 10)).toBe(0)
    expect(clampFloat(99, 0, 10)).toBe(10)
    expect(clampFloat(0, 0, 10)).toBe(0)
    expect(clampFloat(10, 0, 10)).toBe(10)
  })
})

describe('fmtK', () => {
  it('returns an em dash for non-finite input', () => {
    expect(fmtK('abc')).toBe('—')
    expect(fmtK(undefined)).toBe('—')
    expect(fmtK(NaN)).toBe('—')
  })

  it('formats millions with one decimal and an M suffix', () => {
    expect(fmtK(1_000_000)).toBe('1.0M')
    expect(fmtK(2_500_000)).toBe('2.5M')
  })

  it('formats thousands as a rounded k value', () => {
    expect(fmtK(1000)).toBe('1k')
    expect(fmtK(1500)).toBe('2k')
    expect(fmtK(2400)).toBe('2k')
  })

  it('rounds small values to an integer string', () => {
    expect(fmtK(999)).toBe('999')
    expect(fmtK(12.6)).toBe('13')
    expect(fmtK(0)).toBe('0')
  })
})

describe('fmtDuration', () => {
  it('returns an em dash for non-finite input', () => {
    expect(fmtDuration('nope')).toBe('—')
    expect(fmtDuration(undefined)).toBe('—')
  })

  it('renders >= 1000ms as seconds with two decimals', () => {
    expect(fmtDuration(1000)).toBe('1.00s')
    expect(fmtDuration(1500)).toBe('1.50s')
  })

  it('renders sub-second values as rounded milliseconds', () => {
    expect(fmtDuration(250)).toBe('250ms')
    expect(fmtDuration(12.6)).toBe('13ms')
  })
})

describe('fmtTraceArgs', () => {
  it('returns an em dash for nullish input', () => {
    expect(fmtTraceArgs(null)).toBe('—')
    expect(fmtTraceArgs(undefined)).toBe('—')
  })

  it('passes through non-empty strings and dashes empty ones', () => {
    expect(fmtTraceArgs('hello')).toBe('hello')
    expect(fmtTraceArgs('')).toBe('—')
  })

  it('JSON-stringifies objects', () => {
    expect(fmtTraceArgs({ a: 1, b: 'x' })).toBe('{"a":1,"b":"x"}')
  })

  it('truncates long output to 240 chars plus an ellipsis', () => {
    const out = fmtTraceArgs('a'.repeat(300))
    expect(out.length).toBe(241)
    expect(out.endsWith('…')).toBe(true)
    expect(out.startsWith('a'.repeat(240))).toBe(true)
  })
})

describe('quoteShell', () => {
  it('returns empty quotes for blank input', () => {
    expect(quoteShell('')).toBe("''")
    expect(quoteShell(null)).toBe("''")
    expect(quoteShell('   ')).toBe("''")
  })

  it('wraps plain values in single quotes', () => {
    expect(quoteShell('abc')).toBe("'abc'")
  })

  it('escapes embedded single quotes', () => {
    expect(quoteShell("a'b")).toBe("'a'\\''b'")
  })
})

describe('formatTraceCommand', () => {
  it('builds search_paths commands', () => {
    expect(formatTraceCommand({ name: 'search_paths' })).toBe('rg --files')
    expect(formatTraceCommand({ name: 'search_paths', args: { query: 'foo' } })).toBe(
      "rg --files | rg 'foo'"
    )
  })

  it('builds search_tests commands', () => {
    expect(formatTraceCommand({ name: 'search_tests' })).toBe("rg --files | rg 'test|tests|spec'")
    expect(formatTraceCommand({ name: 'search_tests', args: { query: 'foo' } })).toBe(
      "rg --files | rg 'test|tests|spec' | rg 'foo'"
    )
  })

  it('builds search_text commands with query and paths', () => {
    expect(formatTraceCommand({ name: 'search_text' })).toBe('rg -n <pattern>')
    expect(formatTraceCommand({ name: 'search_text', args: { query: 'foo' } })).toBe("rg -n 'foo'")
    expect(
      formatTraceCommand({ name: 'search_text', args: { query: 'foo', paths: ['a.ts', 'b.ts'] } })
    ).toBe("rg -n 'foo' 'a.ts' 'b.ts'")
  })

  it('builds get_file_lines commands', () => {
    expect(
      formatTraceCommand({ name: 'get_file_lines', args: { path: 'a.ts', start_line: 1, end_line: 5 } })
    ).toBe("sed -n '1,5p' 'a.ts'")
    expect(formatTraceCommand({ name: 'get_file_lines' })).toBe('sed -n <start>,<end>p <path>')
  })

  it('builds get_file commands', () => {
    expect(formatTraceCommand({ name: 'get_file', args: { path: 'a.ts' } })).toBe("cat 'a.ts'")
    expect(formatTraceCommand({ name: 'get_file' })).toBe('cat <path>')
  })

  it('falls back to the tool name (or "tool")', () => {
    expect(formatTraceCommand({ name: 'unknown_tool' })).toBe('unknown_tool')
    expect(formatTraceCommand({})).toBe('tool')
  })
})

describe('asStringList', () => {
  it('returns an empty array for non-arrays', () => {
    expect(asStringList(null)).toEqual([])
    expect(asStringList('x')).toEqual([])
    expect(asStringList({})).toEqual([])
  })

  it('keeps trimmed non-empty strings and drops everything else', () => {
    expect(asStringList(['a', ' b ', 1, '', null, 'c'])).toEqual(['a', 'b', 'c'])
    expect(asStringList(['   ', '\t'])).toEqual([])
  })
})
