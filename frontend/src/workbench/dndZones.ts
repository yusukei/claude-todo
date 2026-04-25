/**
 * Pure helpers for the Workbench's 5-zone drop classifier. Kept
 * separate from React so unit tests don't need a render harness.
 */
import type { DropEdge } from './treeUtils'

export type DropZone = DropEdge | 'center'

/** Fraction of width / height that each edge band occupies. The
 *  spec calls out 1/5; keeping the constant here makes it cheap to
 *  tune. */
export const EDGE_FRACTION = 0.2

/** Classify a pointer position inside a tab group's bounding rect.
 *  Returns one of the 5 zones; ``null`` only if the pointer is
 *  outside the rect (caller treats that as "no drop"). */
export function classifyZone(
  rect: { left: number; top: number; right: number; bottom: number },
  pointer: { x: number; y: number },
): DropZone | null {
  if (
    pointer.x < rect.left ||
    pointer.x > rect.right ||
    pointer.y < rect.top ||
    pointer.y > rect.bottom
  ) {
    return null
  }
  const w = rect.right - rect.left
  const h = rect.bottom - rect.top
  // Distance from each edge, normalised to [0, 1].
  const dTop = (pointer.y - rect.top) / h
  const dBottom = (rect.bottom - pointer.y) / h
  const dLeft = (pointer.x - rect.left) / w
  const dRight = (rect.right - pointer.x) / w
  // Pick the edge whose band the pointer is in. The smallest
  // normalised distance wins ties so corners snap to the
  // *nearest* edge rather than always preferring vertical or
  // horizontal.
  const candidates: { zone: DropEdge; d: number }[] = []
  if (dTop < EDGE_FRACTION) candidates.push({ zone: 'top', d: dTop })
  if (dBottom < EDGE_FRACTION) candidates.push({ zone: 'bottom', d: dBottom })
  if (dLeft < EDGE_FRACTION) candidates.push({ zone: 'left', d: dLeft })
  if (dRight < EDGE_FRACTION) candidates.push({ zone: 'right', d: dRight })
  if (candidates.length === 0) return 'center'
  candidates.sort((a, b) => a.d - b.d)
  return candidates[0].zone
}

/** Compute the insertion index in a tab strip given a pointer X and
 *  the bounding rects of the existing tab buttons. Each tab is
 *  bisected at its midpoint; pointer in the left half = insert
 *  before, right half = insert after. */
export function classifyTabInsertIndex(
  pointerX: number,
  tabRects: { left: number; right: number }[],
): number {
  for (let i = 0; i < tabRects.length; i++) {
    const r = tabRects[i]
    const mid = (r.left + r.right) / 2
    if (pointerX < mid) return i
  }
  return tabRects.length
}
