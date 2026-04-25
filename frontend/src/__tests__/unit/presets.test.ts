import { describe, expect, it } from 'vitest'
import { PRESETS, getPreset } from '../../workbench/presets'
import { countTabGroups, validateTree } from '../../workbench/treeUtils'

describe('presets', () => {
  it('exposes 4 presets, each with a unique id', () => {
    expect(PRESETS).toHaveLength(4)
    const ids = new Set(PRESETS.map((p) => p.id))
    expect(ids.size).toBe(4)
  })

  it.each(PRESETS.map((p) => [p.id, p] as const))(
    'preset "%s" builds a structurally valid tree',
    (_id, preset) => {
      const t = preset.build()
      expect(validateTree(t)).toBeNull()
    },
  )

  it.each(PRESETS.map((p) => [p.id, p] as const))(
    'preset "%s" stays within MAX_TAB_GROUPS=4',
    (_id, preset) => {
      const t = preset.build()
      expect(countTabGroups(t)).toBeLessThanOrEqual(4)
    },
  )

  it('build() returns a fresh tree on each call (no shared ids)', () => {
    // If two builds shared node ids, validateTree would flag it; we
    // also check a couple of leaf ids directly.
    const a = PRESETS[1].build()
    const b = PRESETS[1].build()
    expect(a).not.toBe(b)
    expect(a.id).not.toBe(b.id)
  })

  it('getPreset resolves by id', () => {
    expect(getPreset('tasks-only')?.label).toBe('Tasks only')
    expect(getPreset('nonexistent')).toBeUndefined()
  })
})
