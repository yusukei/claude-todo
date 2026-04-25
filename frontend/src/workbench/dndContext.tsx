/**
 * Shared DnD state: which pane is being dragged, which group +
 * sub-zone the pointer is over, where a tabify drop would land.
 *
 * Derived once at the layout root from dnd-kit events and consumed
 * by TabGroup to decide which overlay to highlight and TabStrip to
 * draw the insert-position indicator.
 */
import { createContext, useContext } from 'react'
import type { DropZone } from './dndZones'

export interface DragState {
  /** Pane being dragged (its current home, before drop). */
  active: { paneId: string; sourceGroupId: string } | null
  /** Currently hovered group and resolved zone. ``null`` when the
   *  pointer is outside every group. */
  hover: {
    groupId: string
    zone: DropZone
    /** Insert index for tabify drops, computed from pointer-x vs
     *  the existing tab rects. ``-1`` when zone !== 'center'. */
    insertIndex: number
  } | null
}

const noop: DragState = { active: null, hover: null }
export const DragStateContext = createContext<DragState>(noop)

export function useDragState(): DragState {
  return useContext(DragStateContext)
}

// ── ID helpers ────────────────────────────────────────────────
//
// dnd-kit identifies draggables / droppables by string ids. We use
// short prefixes so runtime debugging is readable without needing
// data: payload introspection.

export const dragId = (paneId: string) => `tab:${paneId}`
export const groupDropId = (groupId: string) => `group:${groupId}`

export const parseDragId = (id: string | number | undefined | null) => {
  if (typeof id !== 'string' || !id.startsWith('tab:')) return null
  return id.slice(4)
}
export const parseGroupDropId = (
  id: string | number | undefined | null,
): string | null => {
  if (typeof id !== 'string' || !id.startsWith('group:')) return null
  return id.slice(6)
}
