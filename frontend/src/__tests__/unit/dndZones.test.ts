import { describe, expect, it } from 'vitest'
import {
  classifyTabInsertIndex,
  classifyZone,
  EDGE_FRACTION,
} from '../../workbench/dndZones'

describe('classifyZone', () => {
  // 100x100 rect at origin so fractions map to whole numbers.
  const rect = { left: 0, top: 0, right: 100, bottom: 100 }
  // 1/5 = 20% so the edge bands span [0, 20] / [80, 100] on each axis.

  it('returns "center" for a pointer in the middle', () => {
    expect(classifyZone(rect, { x: 50, y: 50 })).toBe('center')
  })

  it.each([
    ['top', { x: 50, y: 5 }],
    ['bottom', { x: 50, y: 95 }],
    ['left', { x: 5, y: 50 }],
    ['right', { x: 95, y: 50 }],
  ] as const)('returns %s for the matching edge band', (zone, point) => {
    expect(classifyZone(rect, point)).toBe(zone)
  })

  it('returns the closest edge for a corner pointer', () => {
    // Pointer at (3, 5) is closer to the top edge (5/100=0.05) than
    // to the left edge (3/100=0.03). Wait — left is closer in this
    // case. Confirming: dLeft = 3/100 = 0.03, dTop = 5/100 = 0.05.
    // Smallest wins → left.
    expect(classifyZone(rect, { x: 3, y: 5 })).toBe('left')
    // Symmetric case: pointer further from left, near top.
    expect(classifyZone(rect, { x: 10, y: 1 })).toBe('top')
  })

  it('returns null when the pointer is outside the rect', () => {
    expect(classifyZone(rect, { x: -1, y: 50 })).toBeNull()
    expect(classifyZone(rect, { x: 50, y: 101 })).toBeNull()
  })

  it('respects the documented EDGE_FRACTION constant', () => {
    // The exact boundary should still classify as center because
    // ``< EDGE_FRACTION`` is strict.
    const w = rect.right - rect.left
    const x = rect.left + EDGE_FRACTION * w
    expect(classifyZone(rect, { x, y: 50 })).toBe('center')
  })
})

describe('classifyTabInsertIndex', () => {
  // Three tabs of 100px each, no gaps.
  const tabs = [
    { left: 0, right: 100 },
    { left: 100, right: 200 },
    { left: 200, right: 300 },
  ]

  it('returns 0 for a pointer to the left of all tabs', () => {
    expect(classifyTabInsertIndex(-10, tabs)).toBe(0)
  })

  it('returns 0 when in the left half of the first tab', () => {
    expect(classifyTabInsertIndex(40, tabs)).toBe(0)
  })

  it('returns 1 when in the right half of the first tab', () => {
    expect(classifyTabInsertIndex(60, tabs)).toBe(1)
  })

  it('returns the count when past the last tab', () => {
    expect(classifyTabInsertIndex(999, tabs)).toBe(tabs.length)
  })

  it('returns 0 for an empty strip', () => {
    expect(classifyTabInsertIndex(50, [])).toBe(0)
  })
})
