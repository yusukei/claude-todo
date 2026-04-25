import { describe, expect, it } from 'vitest'
import {
  countTabGroups,
  findPaneLocation,
  findTabsNode,
  makePane,
  makeSplitNode,
  makeTabsNode,
  moveTabToCenter,
  moveTabToEdge,
  removeTab,
  insertTabAt,
  splitGroupWithPane,
} from '../../workbench/treeUtils'

// Tiny builders so each test can describe its starting layout
// declaratively. The pane id mirrors a label so failure messages
// stay readable.
const pane = (label: string) =>
  makePane('tasks', { label } as Record<string, unknown>)

describe('removeTab', () => {
  it('removes a tab from its group and updates activeTabId', () => {
    const a = pane('A')
    const b = pane('B')
    const tree = makeTabsNode([a, b])
    const r = removeTab(tree, a.id)
    expect(r.pane?.id).toBe(a.id)
    expect(r.tree).not.toBeNull()
    if (r.tree?.kind !== 'tabs') throw new Error('expected tabs')
    expect(r.tree.tabs.map((p) => p.id)).toEqual([b.id])
    expect(r.tree.activeTabId).toBe(b.id)
  })

  it('returns null tree when the last tab in the only group is removed', () => {
    const a = pane('A')
    const tree = makeTabsNode([a])
    const r = removeTab(tree, a.id)
    expect(r.tree).toBeNull()
    expect(r.pane?.id).toBe(a.id)
  })

  it('collapses a 2-child split when one child becomes empty', () => {
    const a = pane('A')
    const b = pane('B')
    const left = makeTabsNode([a])
    const right = makeTabsNode([b])
    const tree = makeSplitNode('horizontal', [left, right])
    const r = removeTab(tree, a.id)
    // left collapses → right becomes the new root
    expect(r.tree?.kind).toBe('tabs')
    if (r.tree?.kind !== 'tabs') throw new Error('expected tabs')
    expect(r.tree.id).toBe(right.id)
  })

  it('returns the original tree when paneId is not found', () => {
    const a = pane('A')
    const tree = makeTabsNode([a])
    const r = removeTab(tree, 'nonexistent-id')
    expect(r.tree).toBe(tree)
    expect(r.pane).toBeNull()
  })
})

describe('insertTabAt', () => {
  it('inserts at the given index and activates the new pane', () => {
    const a = pane('A')
    const b = pane('B')
    const c = pane('C')
    const tree = makeTabsNode([a, b])
    const next = insertTabAt(tree, tree.id, c, 1)
    if (next.kind !== 'tabs') throw new Error('expected tabs')
    expect(next.tabs.map((p) => p.id)).toEqual([a.id, c.id, b.id])
    expect(next.activeTabId).toBe(c.id)
  })

  it('clamps a too-large index to the end', () => {
    const a = pane('A')
    const b = pane('B')
    const tree = makeTabsNode([a])
    const next = insertTabAt(tree, tree.id, b, 99)
    if (next.kind !== 'tabs') throw new Error('expected tabs')
    expect(next.tabs[1].id).toBe(b.id)
  })
})

describe('splitGroupWithPane', () => {
  it('places new pane to the right edge as horizontal split, target first', () => {
    const a = pane('A')
    const b = pane('B')
    const tree = makeTabsNode([a])
    const next = splitGroupWithPane(tree, tree.id, 'right', b)
    if (next.kind !== 'split') throw new Error('expected split')
    expect(next.orientation).toBe('horizontal')
    if (next.children[0].kind !== 'tabs' || next.children[1].kind !== 'tabs')
      throw new Error('expected tabs children')
    expect(next.children[0].tabs[0].id).toBe(a.id) // existing first
    expect(next.children[1].tabs[0].id).toBe(b.id) // new on the right
  })

  it('places new pane to the top edge as vertical split, new first', () => {
    const a = pane('A')
    const b = pane('B')
    const tree = makeTabsNode([a])
    const next = splitGroupWithPane(tree, tree.id, 'top', b)
    if (next.kind !== 'split') throw new Error('expected split')
    expect(next.orientation).toBe('vertical')
    if (next.children[0].kind !== 'tabs' || next.children[1].kind !== 'tabs')
      throw new Error('expected tabs children')
    expect(next.children[0].tabs[0].id).toBe(b.id) // new on top
    expect(next.children[1].tabs[0].id).toBe(a.id)
  })
})

describe('moveTabToEdge', () => {
  it('moves a tab from source group to a new split sibling on the right', () => {
    const a = pane('A')
    const b = pane('B')
    const c = pane('C')
    const left = makeTabsNode([a, b])
    const right = makeTabsNode([c])
    const tree = makeSplitNode('horizontal', [left, right])
    const next = moveTabToEdge(tree, b.id, right.id, 'right')
    // Source group keeps A; right group now has a sibling new group with B
    expect(countTabGroups(next)).toBe(3)
    const newLoc = findPaneLocation(next, b.id)
    expect(newLoc).not.toBeNull()
    // The new group should not be the original `right` group.
    expect(newLoc!.groupId).not.toBe(right.id)
  })

  it('refuses to split when at MAX_TAB_GROUPS', () => {
    // Build 4 groups in a vertical split.
    const groups = ['A', 'B', 'C', 'D'].map((l) => makeTabsNode([pane(l)]))
    const tree = makeSplitNode('vertical', groups)
    const movePane = groups[0].tabs[0].id
    const target = groups[1].id
    const next = moveTabToEdge(tree, movePane, target, 'right')
    expect(next).toBe(tree) // unchanged
  })
})

describe('moveTabToCenter', () => {
  it('moves a tab from group A to group B as a new tab', () => {
    const a = pane('A')
    const b = pane('B')
    const c = pane('C')
    const left = makeTabsNode([a, b])
    const right = makeTabsNode([c])
    const tree = makeSplitNode('horizontal', [left, right])
    const next = moveTabToCenter(tree, b.id, right.id, 0)
    // Target group should now contain B at index 0, then C
    const target = findTabsNode(next, right.id)
    expect(target?.tabs.map((t) => t.id)).toEqual([b.id, c.id])
    expect(target?.activeTabId).toBe(b.id)
    // Source group should only have A
    const source = findTabsNode(next, left.id)
    expect(source?.tabs.map((t) => t.id)).toEqual([a.id])
  })

  it('reorders within the same group with adjusted index', () => {
    const a = pane('A')
    const b = pane('B')
    const c = pane('C')
    const tree = makeTabsNode([a, b, c])
    // Move A from index 0 to index 2 — after removal, target index 2
    // is the position right after C, so adjusted = 2 - 1 = 1; A
    // lands between B and C.
    const next = moveTabToCenter(tree, a.id, tree.id, 2)
    if (next.kind !== 'tabs') throw new Error('expected tabs')
    expect(next.tabs.map((t) => t.id)).toEqual([b.id, a.id, c.id])
  })

  it('refuses cross-group center drop when target is at tab cap', () => {
    // Target group has 8 tabs (MAX_TABS_PER_GROUP). Source is a
    // separate group with 1 tab. Moving in should be rejected.
    const targetTabs = Array.from({ length: 8 }, (_, i) => pane(`T${i}`))
    const target = makeTabsNode(targetTabs)
    const source = makeTabsNode([pane('S')])
    const tree = makeSplitNode('horizontal', [source, target])
    const next = moveTabToCenter(tree, source.tabs[0].id, target.id, 0)
    expect(next).toBe(tree)
  })

  it('handles same-group center drop on the same index as a no-op equivalent', () => {
    const a = pane('A')
    const b = pane('B')
    const tree = makeTabsNode([a, b])
    // Move A to index 0 (its current location). After removal index
    // adjusts: 0 < 0 is false, so adjusted = 0; A lands at 0.
    const next = moveTabToCenter(tree, a.id, tree.id, 0)
    if (next.kind !== 'tabs') throw new Error('expected tabs')
    expect(next.tabs.map((t) => t.id)).toEqual([a.id, b.id])
  })
})
