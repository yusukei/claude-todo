import { describe, expect, it } from 'vitest'
import {
  dfsPanes,
  findGroupIdOf,
  focusIndex,
  matchHotkey,
} from '../../workbench/hotkeys'
import {
  makePane,
  makeSplitNode,
  makeTabsNode,
} from '../../workbench/treeUtils'

describe('matchHotkey', () => {
  const ev = (init: KeyboardEventInit): KeyboardEvent =>
    new KeyboardEvent('keydown', init)

  it('matches Cmd/Ctrl+W to close-pane', () => {
    expect(matchHotkey(ev({ metaKey: true, key: 'w' }))).toBe('close-pane')
    expect(matchHotkey(ev({ ctrlKey: true, key: 'w' }))).toBe('close-pane')
  })

  it('does not match Cmd+Shift+W (would shadow split-horizontal style)', () => {
    expect(
      matchHotkey(ev({ metaKey: true, shiftKey: true, key: 'w' })),
    ).toBeNull()
  })

  it('matches Cmd+\\\\ to split-vertical', () => {
    expect(matchHotkey(ev({ metaKey: true, key: '\\' }))).toBe(
      'split-vertical',
    )
  })

  it('matches Cmd+Shift+\\\\ to split-horizontal', () => {
    expect(
      matchHotkey(ev({ metaKey: true, shiftKey: true, key: '\\' })),
    ).toBe('split-horizontal')
  })

  it('matches Cmd+Shift+R to reset-layout, Cmd+R alone does NOT', () => {
    expect(
      matchHotkey(ev({ metaKey: true, shiftKey: true, key: 'r' })),
    ).toBe('reset-layout')
    expect(matchHotkey(ev({ metaKey: true, key: 'r' }))).toBeNull()
  })

  it.each([1, 2, 3, 4])('matches Cmd+%i to focus-%i', (n) => {
    expect(matchHotkey(ev({ metaKey: true, key: String(n) }))).toBe(
      `focus-${n}`,
    )
  })

  it('returns null without a modifier', () => {
    expect(matchHotkey(ev({ key: 'w' }))).toBeNull()
    expect(matchHotkey(ev({ key: '\\' }))).toBeNull()
  })
})

describe('focusIndex', () => {
  it('returns the 1-based index for focus-N', () => {
    expect(focusIndex('focus-1')).toBe(1)
    expect(focusIndex('focus-4')).toBe(4)
  })

  it('returns null for non-focus hotkeys', () => {
    expect(focusIndex('close-pane')).toBeNull()
    expect(focusIndex('split-vertical')).toBeNull()
  })
})

describe('dfsPanes', () => {
  it('returns panes in tree order for a single tab group', () => {
    const a = makePane('tasks')
    const b = makePane('terminal')
    const tree = makeTabsNode([a, b])
    expect(dfsPanes(tree).map((p) => p.id)).toEqual([a.id, b.id])
  })

  it('walks splits depth-first, left-first', () => {
    const a = makePane('tasks')
    const b = makePane('terminal')
    const c = makePane('doc')
    const tree = makeSplitNode('horizontal', [
      makeTabsNode([a, b]),
      makeTabsNode([c]),
    ])
    expect(dfsPanes(tree).map((p) => p.id)).toEqual([a.id, b.id, c.id])
  })
})

describe('findGroupIdOf', () => {
  it('finds the group containing a pane', () => {
    const a = makePane('tasks')
    const b = makePane('terminal')
    const left = makeTabsNode([a])
    const right = makeTabsNode([b])
    const tree = makeSplitNode('horizontal', [left, right])
    expect(findGroupIdOf(tree, a.id)).toBe(left.id)
    expect(findGroupIdOf(tree, b.id)).toBe(right.id)
  })

  it('returns null for an unknown pane id', () => {
    const tree = makeTabsNode([makePane('tasks')])
    expect(findGroupIdOf(tree, 'nope')).toBeNull()
  })
})
