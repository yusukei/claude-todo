/**
 * Drop preview overlay shown over each tab group while a tab drag is
 * in progress. Renders a 5-region grid (top / right / bottom / left
 * edges + center) and highlights the region whose hit-test currently
 * matches the pointer.
 *
 * Hit detection happens in ``WorkbenchLayout`` which forwards the
 * resolved ``activeZone`` here for rendering only — we don't
 * register dnd-kit droppables for the zones, because the pointer
 * coordinate already disambiguates and adding 5 droppables per group
 * inflates the over-collision search for nothing.
 */
import { useMemo } from 'react'
import type { DropZone } from './dndZones'
import { EDGE_FRACTION } from './dndZones'

interface Props {
  active: boolean
  activeZone: DropZone | null
  /** ``true`` when the layout is at MAX_TAB_GROUPS — edge zones
   *  cannot accept the drop and should render as disabled. */
  edgesDisabled: boolean
  /** ``true`` when the destination group is at MAX_TABS_PER_GROUP and
   *  the dragged tab isn't already in this group — center zone
   *  cannot tabify and renders disabled. */
  centerDisabled: boolean
  /** Honour ``prefers-reduced-motion`` — when set, the overlay
   *  appears instantly instead of fading in. */
  reducedMotion: boolean
}

export default function DropZoneOverlay({
  active,
  activeZone,
  edgesDisabled,
  centerDisabled,
  reducedMotion,
}: Props) {
  // Memo to avoid recomputing styles every render while dragging.
  const style = useMemo(
    () =>
      ({
        transition: reducedMotion ? undefined : 'opacity 100ms ease-out',
        opacity: active ? 1 : 0,
        pointerEvents: 'none' as const,
      }) satisfies React.CSSProperties,
    [active, reducedMotion],
  )

  if (!active) return null

  const edgePct = EDGE_FRACTION * 100

  // Per-zone visual tokens. Each zone is a ``<div>`` positioned with
  // absolute / inset. We render *all* zones for clarity (so the user
  // can see the available drop targets), but only the active one
  // gets the saturated fill.
  const baseEdge =
    'absolute pointer-events-none border border-blue-300/50 dark:border-blue-500/40'
  const activeEdge = 'bg-blue-400/30 dark:bg-blue-400/30'
  const disabledEdge = 'bg-gray-400/10 dark:bg-gray-600/10'
  const passiveEdge = 'bg-blue-300/5 dark:bg-blue-300/5'

  const edgeFill = (zone: 'top' | 'right' | 'bottom' | 'left') => {
    if (edgesDisabled) return disabledEdge
    return activeZone === zone ? activeEdge : passiveEdge
  }

  const centerFill = () => {
    if (centerDisabled) return disabledEdge
    return activeZone === 'center' ? activeEdge : passiveEdge
  }

  return (
    <div className="absolute inset-0 z-30" style={style} aria-hidden>
      {/* Top edge */}
      <div
        className={`${baseEdge} ${edgeFill('top')} top-0 left-0 right-0`}
        style={{ height: `${edgePct}%` }}
      />
      {/* Bottom edge */}
      <div
        className={`${baseEdge} ${edgeFill('bottom')} bottom-0 left-0 right-0`}
        style={{ height: `${edgePct}%` }}
      />
      {/* Left edge (between top and bottom strips) */}
      <div
        className={`${baseEdge} ${edgeFill('left')} left-0`}
        style={{
          width: `${edgePct}%`,
          top: `${edgePct}%`,
          bottom: `${edgePct}%`,
        }}
      />
      {/* Right edge */}
      <div
        className={`${baseEdge} ${edgeFill('right')} right-0`}
        style={{
          width: `${edgePct}%`,
          top: `${edgePct}%`,
          bottom: `${edgePct}%`,
        }}
      />
      {/* Center */}
      <div
        className={`${baseEdge} ${centerFill()}`}
        style={{
          left: `${edgePct}%`,
          right: `${edgePct}%`,
          top: `${edgePct}%`,
          bottom: `${edgePct}%`,
        }}
      />
    </div>
  )
}
