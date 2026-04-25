import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import {
  Plus,
  X,
  MoreVertical,
  SplitSquareVertical,
  SplitSquareHorizontal,
  Trash2,
} from 'lucide-react'
import { useDraggable, useDroppable } from '@dnd-kit/core'
import type { TabsNode, Pane, PaneType } from './types'
import { MAX_TABS_PER_GROUP, MAX_TAB_GROUPS } from './types'
import { PANE_TYPE_LABELS } from './paneRegistry'
import PaneFrame from './PaneFrame'
import DropZoneOverlay from './DropZoneOverlay'
import {
  dragId,
  groupDropId,
  useDragState,
} from './dndContext'
import { registerTabStrip } from './WorkbenchLayout'

interface Props {
  group: TabsNode
  projectId: string
  totalGroups: number
  reducedMotion: boolean

  onActivateTab: (groupId: string, tabId: string) => void
  onCloseTab: (groupId: string, tabId: string) => void
  onAddTab: (groupId: string, paneType: PaneType) => void
  onChangePaneType: (paneId: string, paneType: PaneType) => void
  onConfigChange: (paneId: string, patch: Record<string, unknown>) => void
  onSplit: (groupId: string, orientation: 'horizontal' | 'vertical') => void
  onCloseGroup: (groupId: string) => void
}

const SELECTABLE_TYPES: PaneType[] = [
  'tasks',
  'terminal',
  'doc',
  'file-browser',
]

export default function TabGroup({
  group,
  projectId,
  totalGroups,
  reducedMotion,
  onActivateTab,
  onCloseTab,
  onAddTab,
  onChangePaneType,
  onConfigChange,
  onSplit,
  onCloseGroup,
}: Props) {
  const activeTab =
    group.tabs.find((t) => t.id === group.activeTabId) ?? group.tabs[0]
  const [menuOpen, setMenuOpen] = useState(false)
  const [typeMenuOpen, setTypeMenuOpen] = useState(false)

  const canAddTab = group.tabs.length < MAX_TABS_PER_GROUP
  const canSplit = totalGroups < MAX_TAB_GROUPS

  // Drop target: the entire group rect. dnd-kit only resolves which
  // group is hovered; the layout root narrows that to a 5-zone result
  // using the live pointer position.
  const { setNodeRef: setDropRef } = useDroppable({
    id: groupDropId(group.id),
  })

  // ── Tab strip registration for insert-index computation ─────

  const stripRef = useRef<HTMLDivElement>(null)
  const tabRefs = useRef<Map<string, HTMLElement>>(new Map())

  // useLayoutEffect so the registry has up-to-date refs before the
  // next drag move event fires.
  useLayoutEffect(() => {
    const el = stripRef.current
    if (!el) return
    return registerTabStrip(group.id, el, () => {
      // Return tabs in the current visual order. We read from the
      // ref map but iterate via group.tabs to preserve order even
      // after a reorder.
      const out: HTMLElement[] = []
      for (const t of group.tabs) {
        const r = tabRefs.current.get(t.id)
        if (r) out.push(r)
      }
      return out
    })
  }, [group.id, group.tabs])

  // ── Drag state for overlay rendering ────────────────────────

  const dragState = useDragState()
  const isOverlayActive = dragState.active !== null
  const isThisGroupHovered = dragState.hover?.groupId === group.id
  const activeZone = isThisGroupHovered ? dragState.hover!.zone : null
  const insertIndex =
    isThisGroupHovered && dragState.hover!.zone === 'center'
      ? dragState.hover!.insertIndex
      : -1
  const isSourceGroup = dragState.active?.sourceGroupId === group.id
  const centerDisabled =
    !isSourceGroup && group.tabs.length >= MAX_TABS_PER_GROUP
  const edgesDisabled = totalGroups >= MAX_TAB_GROUPS

  return (
    <div
      ref={setDropRef}
      className="relative flex flex-col h-full min-h-0 bg-white dark:bg-gray-900"
    >
      {/* Tab strip */}
      <div className="flex items-stretch h-9 bg-gray-100 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
        <div
          ref={stripRef}
          className="relative flex flex-1 min-w-0 overflow-x-auto"
        >
          {group.tabs.map((tab, i) => (
            <DraggableTab
              key={tab.id}
              tab={tab}
              isActive={tab.id === group.activeTabId}
              registerRef={(el) => {
                if (el) tabRefs.current.set(tab.id, el)
                else tabRefs.current.delete(tab.id)
              }}
              onActivate={() => onActivateTab(group.id, tab.id)}
              onClose={() => onCloseTab(group.id, tab.id)}
            >
              {/* Insertion indicator: a thin vertical line at the
                  active drop position drawn between tabs. */}
              {insertIndex === i && <InsertIndicator />}
            </DraggableTab>
          ))}
          {/* Tail insert indicator when dropping after the last tab */}
          {insertIndex === group.tabs.length && <InsertIndicator />}
          {/* New tab button */}
          <button
            type="button"
            onClick={() => onAddTab(group.id, activeTab.paneType)}
            disabled={!canAddTab}
            className="px-2 text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 disabled:opacity-40 disabled:cursor-not-allowed"
            title={
              canAddTab
                ? 'New tab (same type)'
                : `Tab cap reached (${MAX_TABS_PER_GROUP})`
            }
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Group menu */}
        <div className="relative flex items-stretch">
          <button
            type="button"
            onClick={() => {
              setMenuOpen((v) => !v)
              setTypeMenuOpen(false)
            }}
            className="px-2 text-gray-500 hover:text-gray-800 dark:hover:text-gray-200"
            aria-label="Pane menu"
          >
            <MoreVertical className="w-4 h-4" />
          </button>
          {menuOpen && (
            <div
              className="absolute right-0 top-full z-20 mt-1 w-56 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg text-xs"
              onMouseLeave={() => {
                setMenuOpen(false)
                setTypeMenuOpen(false)
              }}
            >
              <MenuItem
                icon={<SplitSquareVertical className="w-3.5 h-3.5" />}
                label="Split right"
                disabled={!canSplit}
                disabledHint={`Max ${MAX_TAB_GROUPS} panes`}
                onClick={() => {
                  setMenuOpen(false)
                  onSplit(group.id, 'horizontal')
                }}
              />
              <MenuItem
                icon={<SplitSquareHorizontal className="w-3.5 h-3.5" />}
                label="Split down"
                disabled={!canSplit}
                disabledHint={`Max ${MAX_TAB_GROUPS} panes`}
                onClick={() => {
                  setMenuOpen(false)
                  onSplit(group.id, 'vertical')
                }}
              />
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setTypeMenuOpen((v) => !v)}
                  className="w-full text-left px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-700 flex items-center justify-between"
                >
                  <span>Change type ({PANE_TYPE_LABELS[activeTab.paneType]})</span>
                  <span className="text-gray-400">▸</span>
                </button>
                {typeMenuOpen && (
                  <div className="absolute right-full top-0 mr-1 w-44 rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 shadow-lg">
                    {SELECTABLE_TYPES.map((t) => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => {
                          setMenuOpen(false)
                          setTypeMenuOpen(false)
                          onChangePaneType(activeTab.id, t)
                        }}
                        disabled={t === activeTab.paneType}
                        className="w-full text-left px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {PANE_TYPE_LABELS[t]}
                        {t === activeTab.paneType && (
                          <span className="text-gray-400 ml-1">(current)</span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div className="border-t border-gray-200 dark:border-gray-700 my-1" />
              <MenuItem
                icon={<Trash2 className="w-3.5 h-3.5 text-red-500" />}
                label="Close group"
                onClick={() => {
                  setMenuOpen(false)
                  onCloseGroup(group.id)
                }}
              />
            </div>
          )}
        </div>
      </div>

      {/* Active pane body. Wrapped so the overlay can sit absolutely
          over it without obscuring the tab strip. */}
      <div className="relative flex-1 min-h-0">
        <PaneFrame
          key={activeTab.id}
          pane={activeTab}
          projectId={projectId}
          onConfigChange={onConfigChange}
        />
        <DropZoneOverlay
          active={isOverlayActive}
          activeZone={activeZone}
          edgesDisabled={edgesDisabled}
          centerDisabled={centerDisabled}
          reducedMotion={reducedMotion}
        />
      </div>
    </div>
  )
}

// ── DraggableTab ──────────────────────────────────────────────

interface DraggableTabProps {
  tab: Pane
  isActive: boolean
  registerRef: (el: HTMLElement | null) => void
  onActivate: () => void
  onClose: () => void
  children?: React.ReactNode
}

function DraggableTab({
  tab,
  isActive,
  registerRef,
  onActivate,
  onClose,
  children,
}: DraggableTabProps) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: dragId(tab.id),
    data: { paneId: tab.id, paneType: tab.paneType },
  })

  // Compose dnd-kit's ref with our local ref for the strip registry.
  const composedRef = (el: HTMLButtonElement | null) => {
    setNodeRef(el)
    registerRef(el)
  }

  // Hide the *source* tab while it's dragging — the DragOverlay
  // renders the moving copy. (We don't fully unmount because the
  // adjacent tabs would reflow and the activator rect would be
  // stale.) Visibility:hidden preserves layout.
  const draggingStyle = isDragging
    ? { opacity: 0, pointerEvents: 'none' as const }
    : undefined

  // ``useEffect`` only to keep ESLint happy about ``registerRef``
  // dependencies; the work happens in the ref callback above.
  useEffect(() => () => registerRef(null), [registerRef])

  return (
    <>
      {children}
      <button
        ref={composedRef}
        {...attributes}
        {...listeners}
        type="button"
        onClick={(e) => {
          // dnd-kit's listeners don't suppress clicks below the
          // activation distance, so this fires for short-distance
          // pointer up events. Treat it as activate.
          if ((e as { defaultPrevented?: boolean }).defaultPrevented) return
          onActivate()
        }}
        onAuxClick={(e) => {
          if (e.button === 1) {
            e.preventDefault()
            onClose()
          }
        }}
        style={draggingStyle}
        className={`group flex items-center gap-1.5 px-3 text-xs border-r border-gray-200 dark:border-gray-700 max-w-[14rem] flex-shrink-0 select-none cursor-grab active:cursor-grabbing ${
          isActive
            ? 'bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100'
            : 'text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700'
        }`}
        title={PANE_TYPE_LABELS[tab.paneType]}
      >
        <span className="truncate">{PANE_TYPE_LABELS[tab.paneType]}</span>
        <span
          role="button"
          tabIndex={0}
          // Stop the close affordance from initiating a drag —
          // dnd-kit treats *any* pointerdown on the draggable as a
          // potential drag start, which would block the click that
          // follows. Capturing here keeps the listener from seeing
          // the event.
          onPointerDownCapture={(e) => {
            e.stopPropagation()
          }}
          onClick={(e) => {
            e.stopPropagation()
            onClose()
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.stopPropagation()
              onClose()
            }
          }}
          className="opacity-0 group-hover:opacity-100 hover:bg-gray-300 dark:hover:bg-gray-600 rounded p-0.5"
          aria-label="Close tab"
        >
          <X className="w-3 h-3" />
        </span>
      </button>
    </>
  )
}

// ── InsertIndicator ───────────────────────────────────────────

function InsertIndicator() {
  return (
    <span
      className="self-stretch w-0.5 bg-blue-500 dark:bg-blue-400 mx-0 flex-shrink-0"
      aria-hidden
    />
  )
}

// ── MenuItem ──────────────────────────────────────────────────

interface MenuItemProps {
  icon: React.ReactNode
  label: string
  disabled?: boolean
  disabledHint?: string
  onClick: () => void
}

function MenuItem({ icon, label, disabled, disabledHint, onClick }: MenuItemProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={disabled ? disabledHint : undefined}
      className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-transparent"
    >
      {icon}
      <span>{label}</span>
    </button>
  )
}
