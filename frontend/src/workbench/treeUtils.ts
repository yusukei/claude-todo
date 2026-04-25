/**
 * Pure functions over LayoutTree.
 *
 * All mutations are non-destructive: they return a new tree (or the
 * same reference if nothing changed) so React's referential equality
 * stays honest and ``debounceSave`` can compare cheaply.
 */
import type {
  LayoutTree,
  Pane,
  PaneType,
  SplitNode,
  TabsNode,
} from './types'
import { MAX_TAB_GROUPS, MAX_TABS_PER_GROUP } from './types'

const newId = (): string =>
  // crypto.randomUUID is part of the Web Crypto API on every modern
  // browser; fall back to a Math.random shim for the unit-test JSDOM
  // environment which doesn't ship it.
  typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `id-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`

// ── Construction ──────────────────────────────────────────────

export function makePane(
  paneType: PaneType,
  paneConfig: Record<string, unknown> = {},
): Pane {
  return { id: newId(), paneType, paneConfig }
}

export function makeTabsNode(tabs: Pane[]): TabsNode {
  if (tabs.length === 0) {
    throw new Error('makeTabsNode: at least one tab is required')
  }
  return {
    id: newId(),
    kind: 'tabs',
    tabs,
    activeTabId: tabs[0].id,
  }
}

export function makeSplitNode(
  orientation: 'horizontal' | 'vertical',
  children: LayoutTree[],
): SplitNode {
  if (children.length < 2) {
    throw new Error('makeSplitNode: at least two children are required')
  }
  return {
    id: newId(),
    kind: 'split',
    orientation,
    children,
    sizes: equalSizes(children.length),
  }
}

/** Default layout: a single tab group with one Tasks pane. */
export function defaultLayout(): LayoutTree {
  return makeTabsNode([makePane('tasks', {})])
}

// ── Counting / queries ────────────────────────────────────────

export function countTabGroups(tree: LayoutTree): number {
  if (tree.kind === 'tabs') return 1
  return tree.children.reduce((acc, c) => acc + countTabGroups(c), 0)
}

export function findTabsNode(
  tree: LayoutTree,
  id: string,
): TabsNode | null {
  if (tree.kind === 'tabs') return tree.id === id ? tree : null
  for (const child of tree.children) {
    const found = findTabsNode(child, id)
    if (found) return found
  }
  return null
}

export function findPaneLocation(
  tree: LayoutTree,
  paneId: string,
): { groupId: string; tabIndex: number } | null {
  if (tree.kind === 'tabs') {
    const idx = tree.tabs.findIndex((t) => t.id === paneId)
    return idx >= 0 ? { groupId: tree.id, tabIndex: idx } : null
  }
  for (const child of tree.children) {
    const found = findPaneLocation(child, paneId)
    if (found) return found
  }
  return null
}

// ── Sizes ──────────────────────────────────────────────────────

function equalSizes(n: number): number[] {
  if (n <= 0) return []
  const each = 100 / n
  const sizes = Array.from({ length: n }, () => each)
  // Compensate for float drift on the last entry so the sum is
  // exactly 100 (react-resizable-panels validates this).
  const sum = sizes.reduce((a, b) => a + b, 0)
  sizes[n - 1] += 100 - sum
  return sizes
}

/** Renormalise the sizes array so it sums to 100, preserving ratios.
 *  No-op when already valid. */
export function normaliseSizes(sizes: number[]): number[] {
  if (sizes.length === 0) return sizes
  const sum = sizes.reduce((a, b) => a + b, 0)
  if (sum <= 0) return equalSizes(sizes.length)
  if (Math.abs(sum - 100) < 0.01) return sizes
  const k = 100 / sum
  const scaled = sizes.map((s) => s * k)
  // Drift-correct on the last element.
  const newSum = scaled.reduce((a, b) => a + b, 0)
  scaled[scaled.length - 1] += 100 - newSum
  return scaled
}

/** Walk the tree and renormalise every split's sizes. */
export function normaliseTree(tree: LayoutTree): LayoutTree {
  if (tree.kind === 'tabs') return tree
  const children = tree.children.map(normaliseTree)
  return {
    ...tree,
    children,
    sizes: normaliseSizes(tree.sizes.length === children.length
      ? tree.sizes
      : equalSizes(children.length)),
  }
}

// ── Mutations: tabs ───────────────────────────────────────────

export function addTab(
  tree: LayoutTree,
  groupId: string,
  pane: Pane,
): LayoutTree {
  if (tree.kind === 'tabs') {
    if (tree.id !== groupId) return tree
    if (tree.tabs.length >= MAX_TABS_PER_GROUP) return tree
    return { ...tree, tabs: [...tree.tabs, pane], activeTabId: pane.id }
  }
  return {
    ...tree,
    children: tree.children.map((c) => addTab(c, groupId, pane)),
  }
}

export function setActiveTab(
  tree: LayoutTree,
  groupId: string,
  tabId: string,
): LayoutTree {
  if (tree.kind === 'tabs') {
    if (tree.id !== groupId) return tree
    if (!tree.tabs.some((t) => t.id === tabId)) return tree
    return { ...tree, activeTabId: tabId }
  }
  return {
    ...tree,
    children: tree.children.map((c) => setActiveTab(c, groupId, tabId)),
  }
}

export function updatePaneConfig(
  tree: LayoutTree,
  paneId: string,
  patch: Record<string, unknown>,
): LayoutTree {
  if (tree.kind === 'tabs') {
    let changed = false
    const tabs = tree.tabs.map((t) => {
      if (t.id !== paneId) return t
      changed = true
      return { ...t, paneConfig: { ...t.paneConfig, ...patch } }
    })
    return changed ? { ...tree, tabs } : tree
  }
  return {
    ...tree,
    children: tree.children.map((c) => updatePaneConfig(c, paneId, patch)),
  }
}

export function changePaneType(
  tree: LayoutTree,
  paneId: string,
  paneType: PaneType,
  initialConfig: Record<string, unknown> = {},
): LayoutTree {
  if (tree.kind === 'tabs') {
    let changed = false
    const tabs = tree.tabs.map((t) => {
      if (t.id !== paneId) return t
      changed = true
      return { ...t, paneType, paneConfig: initialConfig }
    })
    return changed ? { ...tree, tabs } : tree
  }
  return {
    ...tree,
    children: tree.children.map((c) =>
      changePaneType(c, paneId, paneType, initialConfig),
    ),
  }
}

/** Close a tab. Returns ``null`` when the tree should be replaced
 *  with the default layout (closing the last tab of the last group).
 */
export function closeTab(
  tree: LayoutTree,
  groupId: string,
  tabId: string,
): LayoutTree | null {
  const result = closeTabInner(tree, groupId, tabId)
  if (result === undefined) return tree // not found
  return result
}

function closeTabInner(
  tree: LayoutTree,
  groupId: string,
  tabId: string,
): LayoutTree | null | undefined {
  if (tree.kind === 'tabs') {
    if (tree.id !== groupId) return undefined
    const idx = tree.tabs.findIndex((t) => t.id === tabId)
    if (idx < 0) return undefined
    const remaining = [...tree.tabs.slice(0, idx), ...tree.tabs.slice(idx + 1)]
    if (remaining.length === 0) {
      return null // signal: remove this group
    }
    let activeTabId = tree.activeTabId
    if (activeTabId === tabId) {
      activeTabId = remaining[Math.min(idx, remaining.length - 1)].id
    }
    return { ...tree, tabs: remaining, activeTabId }
  }
  // Recurse, then collapse if a child was removed.
  let changed = false
  const newChildren: LayoutTree[] = []
  for (const child of tree.children) {
    const r = closeTabInner(child, groupId, tabId)
    if (r === undefined) {
      newChildren.push(child)
    } else if (r === null) {
      changed = true
      // child removed entirely
    } else {
      changed = true
      newChildren.push(r)
    }
  }
  if (!changed) return undefined
  if (newChildren.length === 0) return null
  if (newChildren.length === 1) return newChildren[0] // collapse split
  return {
    ...tree,
    children: newChildren,
    sizes: equalSizes(newChildren.length),
  }
}

// ── Mutations: splits ─────────────────────────────────────────

/** Split an existing tab group into two side-by-side groups. The
 *  original group keeps its tabs; a new empty group is created next
 *  to it with one fresh tab of ``newPaneType``.
 *
 *  Returns the original tree if splitting would exceed
 *  ``MAX_TAB_GROUPS``. */
export function splitTabGroup(
  tree: LayoutTree,
  groupId: string,
  orientation: 'horizontal' | 'vertical',
  newPaneType: PaneType,
  newPaneConfig: Record<string, unknown> = {},
): LayoutTree {
  if (countTabGroups(tree) >= MAX_TAB_GROUPS) return tree
  return splitTabGroupInner(
    tree,
    groupId,
    orientation,
    makePane(newPaneType, newPaneConfig),
  )
}

function splitTabGroupInner(
  tree: LayoutTree,
  groupId: string,
  orientation: 'horizontal' | 'vertical',
  newPane: Pane,
): LayoutTree {
  if (tree.kind === 'tabs') {
    if (tree.id !== groupId) return tree
    const newGroup = makeTabsNode([newPane])
    return makeSplitNode(orientation, [tree, newGroup])
  }
  return {
    ...tree,
    children: tree.children.map((c) =>
      splitTabGroupInner(c, groupId, orientation, newPane),
    ),
  }
}

export function setSplitSizes(
  tree: LayoutTree,
  splitId: string,
  sizes: number[],
): LayoutTree {
  if (tree.kind === 'tabs') return tree
  if (tree.id === splitId) {
    return { ...tree, sizes: normaliseSizes(sizes) }
  }
  return {
    ...tree,
    children: tree.children.map((c) => setSplitSizes(c, splitId, sizes)),
  }
}

// ── Mutations: drag-and-drop moves ────────────────────────────

/**
 * Drop edges. ``top`` / ``bottom`` produce a vertical split (children
 * stacked top-to-bottom); ``left`` / ``right`` produce a horizontal
 * split (children placed side-by-side).
 */
export type DropEdge = 'top' | 'right' | 'bottom' | 'left'

/** Convert a drop edge to the orientation of the split it creates. */
function edgeOrientation(edge: DropEdge): 'horizontal' | 'vertical' {
  return edge === 'left' || edge === 'right' ? 'horizontal' : 'vertical'
}

/** ``true`` when the new group ends up *before* the existing target
 *  in tree order (top / left). Drives child placement order in the
 *  produced split. */
function edgePlacesNewFirst(edge: DropEdge): boolean {
  return edge === 'top' || edge === 'left'
}

interface RemoveResult {
  /** New tree (or ``null`` when the operation would empty the entire
   *  layout — caller decides what to do, typically replace with the
   *  default layout). */
  tree: LayoutTree | null
  /** The pane that was removed, ready to be re-inserted. ``null`` if
   *  the pane id wasn't found. */
  pane: Pane | null
}

/** Remove a pane from wherever it lives in the tree. Empty groups
 *  collapse the same way ``closeTab`` handles them. The caller is
 *  expected to insert the pane back somewhere (or drop the result if
 *  the move is purely a delete). */
export function removeTab(tree: LayoutTree, paneId: string): RemoveResult {
  let removed: Pane | null = null
  function visit(t: LayoutTree): LayoutTree | null | undefined {
    if (t.kind === 'tabs') {
      const idx = t.tabs.findIndex((p) => p.id === paneId)
      if (idx < 0) return undefined
      removed = t.tabs[idx]
      const remaining = [...t.tabs.slice(0, idx), ...t.tabs.slice(idx + 1)]
      if (remaining.length === 0) return null
      let activeTabId = t.activeTabId
      if (activeTabId === paneId) {
        activeTabId = remaining[Math.min(idx, remaining.length - 1)].id
      }
      return { ...t, tabs: remaining, activeTabId }
    }
    let changed = false
    const newChildren: LayoutTree[] = []
    for (const c of t.children) {
      const r = visit(c)
      if (r === undefined) {
        newChildren.push(c)
      } else if (r === null) {
        changed = true // child collapsed
      } else {
        changed = true
        newChildren.push(r)
      }
    }
    if (!changed) return undefined
    if (newChildren.length === 0) return null
    if (newChildren.length === 1) return newChildren[0]
    return {
      ...t,
      children: newChildren,
      sizes: equalSizes(newChildren.length),
    }
  }
  const r = visit(tree)
  if (r === undefined) return { tree, pane: null }
  return { tree: r, pane: removed }
}

/** Insert a pane into ``groupId`` at ``index``. ``index`` is clamped
 *  into ``[0, group.tabs.length]``. Activates the inserted pane. The
 *  tab cap (``MAX_TABS_PER_GROUP``) is enforced — over the cap the
 *  call is a no-op. */
export function insertTabAt(
  tree: LayoutTree,
  groupId: string,
  pane: Pane,
  index: number,
): LayoutTree {
  if (tree.kind === 'tabs') {
    if (tree.id !== groupId) return tree
    if (tree.tabs.length >= MAX_TABS_PER_GROUP) return tree
    const i = Math.max(0, Math.min(index, tree.tabs.length))
    const tabs = [...tree.tabs.slice(0, i), pane, ...tree.tabs.slice(i)]
    return { ...tree, tabs, activeTabId: pane.id }
  }
  return {
    ...tree,
    children: tree.children.map((c) => insertTabAt(c, groupId, pane, index)),
  }
}

/** Replace the subtree rooted at ``targetGroupId`` with a split node
 *  whose children are (1) the target group and (2) a new tab group
 *  containing ``newPane``, placed on the requested edge. Sizes reset
 *  to 50/50.
 *
 *  Returns the original tree if the target id isn't found. Group cap
 *  is the caller's responsibility. */
export function splitGroupWithPane(
  tree: LayoutTree,
  targetGroupId: string,
  edge: DropEdge,
  newPane: Pane,
): LayoutTree {
  if (tree.kind === 'tabs') {
    if (tree.id !== targetGroupId) return tree
    const newGroup = makeTabsNode([newPane])
    const orientation = edgeOrientation(edge)
    const children = edgePlacesNewFirst(edge)
      ? [newGroup, tree as LayoutTree]
      : [tree as LayoutTree, newGroup]
    return makeSplitNode(orientation, children)
  }
  return {
    ...tree,
    children: tree.children.map((c) =>
      splitGroupWithPane(c, targetGroupId, edge, newPane),
    ),
  }
}

/**
 * High-level drag-and-drop primitive: move ``paneId`` to the requested
 * ``edge`` of ``targetGroupId``. The pane is removed from its current
 * location first; if removing it would leave the target group dangling
 * (e.g. the source pane was the only tab in the target group, so the
 * group disappears) the operation degenerates correctly:
 *
 *  - source group collapses → target may shift in the tree but its id
 *    survives, so the split still attaches around it.
 *  - target group collapses *because of* the removal → no-op
 *    (the move would split into a non-existent group); we return the
 *    original tree.
 *
 * Group cap (``MAX_TAB_GROUPS``) is enforced. If the cap is already
 * met *and* the move would not be a same-group reshuffle, returns the
 * original tree.
 */
export function moveTabToEdge(
  tree: LayoutTree,
  paneId: string,
  targetGroupId: string,
  edge: DropEdge,
): LayoutTree {
  // Cap check: an edge drop always creates a new group, so refuse if
  // the layout is already full.
  if (countTabGroups(tree) >= MAX_TAB_GROUPS) return tree

  const removal = removeTab(tree, paneId)
  if (!removal.pane || removal.tree === null) return tree

  // Verify the target group still exists after removal (edge case:
  // the dragged pane was the last tab of the target group → target
  // disappeared during removal). In that case we just keep the pane
  // in place.
  if (!findTabsNode(removal.tree, targetGroupId)) return tree

  return splitGroupWithPane(removal.tree, targetGroupId, edge, removal.pane)
}

/**
 * High-level drag-and-drop primitive: tabify ``paneId`` into
 * ``targetGroupId`` at ``targetIndex``. Same-group case is handled
 * (acts as reorder); ``targetIndex`` is interpreted *after* the source
 * pane has been removed, so passing the pane's current index leaves
 * it where it is.
 *
 * Tab cap (``MAX_TABS_PER_GROUP``) is enforced. If the destination is
 * already at cap and the move isn't a same-group reorder, returns the
 * original tree.
 */
export function moveTabToCenter(
  tree: LayoutTree,
  paneId: string,
  targetGroupId: string,
  targetIndex: number,
): LayoutTree {
  // Find current location to detect same-group reorders.
  const currentLoc = findPaneLocation(tree, paneId)
  if (!currentLoc) return tree

  // Same-group reorder: remove + reinsert at adjusted index.
  if (currentLoc.groupId === targetGroupId) {
    const removal = removeTab(tree, paneId)
    if (!removal.pane || removal.tree === null) return tree
    // After removing, if the surviving group still has the same id,
    // we can reinsert. (Single-tab groups disappear on remove; that
    // case is a no-op.)
    if (!findTabsNode(removal.tree, targetGroupId)) return tree
    // Adjust index: removing from before the target index shifts it
    // left by one.
    const adjusted =
      currentLoc.tabIndex < targetIndex ? targetIndex - 1 : targetIndex
    return insertTabAt(removal.tree, targetGroupId, removal.pane, adjusted)
  }

  // Cross-group move: enforce cap on destination first.
  const target = findTabsNode(tree, targetGroupId)
  if (!target) return tree
  if (target.tabs.length >= MAX_TABS_PER_GROUP) return tree

  const removal = removeTab(tree, paneId)
  if (!removal.pane || removal.tree === null) return tree
  if (!findTabsNode(removal.tree, targetGroupId)) return tree

  return insertTabAt(removal.tree, targetGroupId, removal.pane, targetIndex)
}

// ── Validation ────────────────────────────────────────────────

/** Verify the tree's structural invariants. Returns ``null`` on
 *  success or an error message on the first detected violation. */
export function validateTree(tree: unknown): string | null {
  return validateTreeInner(tree, new Set<string>())
}

function validateTreeInner(t: unknown, seenIds: Set<string>): string | null {
  if (!t || typeof t !== 'object') return 'expected object'
  const node = t as { id?: unknown; kind?: unknown }
  if (typeof node.id !== 'string' || !node.id) return 'missing id'
  if (seenIds.has(node.id)) return `duplicate id: ${node.id}`
  seenIds.add(node.id)
  if (node.kind === 'tabs') {
    const tabs = (t as TabsNode).tabs
    const activeTabId = (t as TabsNode).activeTabId
    if (!Array.isArray(tabs) || tabs.length === 0) return 'tabs must be non-empty'
    if (typeof activeTabId !== 'string') return 'activeTabId must be a string'
    if (!tabs.some((p) => p && (p as Pane).id === activeTabId))
      return 'activeTabId not found in tabs'
    for (const p of tabs) {
      if (!p || typeof p !== 'object') return 'tab must be object'
      const pane = p as Pane
      if (typeof pane.id !== 'string' || !pane.id) return 'pane missing id'
      if (seenIds.has(pane.id)) return `duplicate pane id: ${pane.id}`
      seenIds.add(pane.id)
      if (typeof pane.paneType !== 'string') return 'paneType missing'
      if (typeof pane.paneConfig !== 'object' || pane.paneConfig === null)
        return 'paneConfig must be object'
    }
    return null
  }
  if (node.kind === 'split') {
    const split = t as SplitNode
    if (split.orientation !== 'horizontal' && split.orientation !== 'vertical')
      return 'invalid orientation'
    if (!Array.isArray(split.children) || split.children.length < 2)
      return 'split needs >= 2 children'
    if (!Array.isArray(split.sizes) || split.sizes.length !== split.children.length)
      return 'sizes length mismatch'
    for (const c of split.children) {
      const e = validateTreeInner(c, seenIds)
      if (e) return e
    }
    return null
  }
  return `unknown kind: ${String(node.kind)}`
}

/** Replace any pane whose paneType isn't in ``known`` with an
 *  ``unsupported`` placeholder so the tree never references a
 *  non-existent pane component. */
export function sanitiseUnknownPaneTypes(
  tree: LayoutTree,
  known: Set<PaneType>,
): LayoutTree {
  if (tree.kind === 'tabs') {
    let changed = false
    const tabs = tree.tabs.map((t) => {
      if (known.has(t.paneType)) return t
      changed = true
      return {
        ...t,
        paneType: 'unsupported' as PaneType,
        paneConfig: { originalType: t.paneType },
      }
    })
    return changed ? { ...tree, tabs } : tree
  }
  return {
    ...tree,
    children: tree.children.map((c) => sanitiseUnknownPaneTypes(c, known)),
  }
}
