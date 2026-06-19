import { describe, expect, it } from 'vitest'

import { baseName, clamp } from './GraphCanvas.helpers'

describe('clamp', () => {
  it('clamps to the inclusive [lo, hi] range', () => {
    expect(clamp(5, 0, 10)).toBe(5)
    expect(clamp(-3, 0, 10)).toBe(0)
    expect(clamp(99, 0, 10)).toBe(10)
    expect(clamp(0, 0, 10)).toBe(0)
    expect(clamp(10, 0, 10)).toBe(10)
  })
})

describe('baseName', () => {
  it('returns the last path segment', () => {
    expect(baseName('src/features/graph/GraphCanvas.tsx')).toBe('GraphCanvas.tsx')
    expect(baseName('main.ts')).toBe('main.ts')
  })

  it('falls back to the whole string when there is no trailing segment', () => {
    expect(baseName('src/')).toBe('src/')
    expect(baseName('')).toBe('')
  })

  it('coerces nullish input to an empty string', () => {
    expect(baseName(undefined as unknown as string)).toBe('')
    expect(baseName(null as unknown as string)).toBe('')
  })
})
