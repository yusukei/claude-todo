/**
 * Workbench layout types.
 *
 * The layout is a tree where every leaf is a "tab group" (one or more
 * panes shown as tabs in the same area) and inner nodes are
 * splits (horizontal or vertical) of two or more children.
 *
 * Every node carries a stable ``id`` (UUID) so React-resizable-panels
 * can track per-node layout state across re-renders, and so DnD
 * targeting (PR3.5) can address a node without relying on tree
 * traversal indices.
 */

export type PaneType =
  | 'tasks'
  | 'task-detail'
  | 'terminal'
  | 'doc'
  | 'documents'
  | 'file-browser'
  | 'error-tracker'
  | 'unsupported'

export interface Pane {
  /** Stable UUID — distinct from the LayoutTree node id. */
  id: string
  paneType: PaneType
  /**
   * Pane-type-specific configuration (e.g. ``viewMode`` for tasks,
   * ``sessionId`` for terminal). Persisted alongside the layout so a
   * reload restores the per-pane state.
   */
  paneConfig: Record<string, unknown>
}

export interface SplitNode {
  id: string
  kind: 'split'
  orientation: 'horizontal' | 'vertical'
  children: LayoutTree[]
  /** 0..100 percentages summing (approximately) to 100. */
  sizes: number[]
}

export interface TabsNode {
  id: string
  kind: 'tabs'
  tabs: Pane[]
  /** Must reference the ``id`` of one of ``tabs``. */
  activeTabId: string
}

export type LayoutTree = SplitNode | TabsNode

/** Wire format persisted to localStorage. */
export interface PersistedLayout {
  version: 1
  /** Wall-clock ms when the layout was last written, used for
   *  last-write-wins reconciliation across browser tabs. */
  savedAt: number
  tree: LayoutTree
}

/** Hard caps to keep the UI sane. */
export const MAX_TAB_GROUPS = 4
export const MAX_TABS_PER_GROUP = 8

/** Schema version of the persisted JSON. Bump on incompatible
 *  changes; the loader falls back to the default layout when the
 *  version doesn't match. */
export const LAYOUT_SCHEMA_VERSION = 1
