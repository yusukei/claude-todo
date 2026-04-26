/**
 * Per-tab client identifier (P1).
 *
 * The `workbench:clientId` lives in `sessionStorage` so it survives a
 * reload of the same tab but is unique across tabs. Other parts of
 * the system (server PUT body, SSE echo skip) depend on this id
 * being stable for the lifetime of a tab.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { getOrCreateClientId } from '../../workbench/storage'

afterEach(() => {
  try {
    window.sessionStorage.removeItem('workbench:clientId')
  } catch {
    /* ignore */
  }
})

describe('Workbench / Persistence — P1: per-tab client id', () => {
  it('first read on a fresh tab generates a UUID-shaped string', () => {
    expect(window.sessionStorage.getItem('workbench:clientId')).toBeNull()
    const id = getOrCreateClientId()
    expect(typeof id).toBe('string')
    // RFC 4122 v4-ish: 8-4-4-4-12 hex with a `4` in the version slot.
    expect(id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    )
  })

  it('persists the id in sessionStorage', () => {
    const id = getOrCreateClientId()
    expect(window.sessionStorage.getItem('workbench:clientId')).toBe(id)
  })

  it('repeat reads in the same tab return the same value', () => {
    const a = getOrCreateClientId()
    const b = getOrCreateClientId()
    const c = getOrCreateClientId()
    expect(a).toBe(b)
    expect(b).toBe(c)
  })

  it('returns the existing value when sessionStorage already has one', () => {
    window.sessionStorage.setItem('workbench:clientId', 'preset-id-xyz')
    expect(getOrCreateClientId()).toBe('preset-id-xyz')
  })
})
