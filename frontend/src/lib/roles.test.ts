import { describe, expect, it } from 'vitest'

import { roleAtLeast } from './roles'

describe('roleAtLeast', () => {
  it('honors the viewer<member<admin<owner hierarchy', () => {
    expect(roleAtLeast('owner', 'admin')).toBe(true)
    expect(roleAtLeast('admin', 'admin')).toBe(true)
    expect(roleAtLeast('member', 'admin')).toBe(false)
    expect(roleAtLeast('viewer', 'admin')).toBe(false)
    expect(roleAtLeast('member', 'viewer')).toBe(true)
  })

  it('treats unknown or missing roles as insufficient', () => {
    expect(roleAtLeast(undefined, 'admin')).toBe(false)
    expect(roleAtLeast(null, 'admin')).toBe(false)
    expect(roleAtLeast('superuser', 'admin')).toBe(false)
    expect(roleAtLeast('admin', 'superuser')).toBe(false)
  })
})
