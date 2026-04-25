import { useState } from 'react'
import {
  Plus,
  X,
  MoreVertical,
  SplitSquareVertical,
  SplitSquareHorizontal,
  Trash2,
} from 'lucide-react'
import type { TabsNode, PaneType } from './types'
import { MAX_TABS_PER_GROUP, MAX_TAB_GROUPS } from './types'
import { PANE_TYPE_LABELS } from './paneRegistry'
import PaneFrame from './PaneFrame'

interface Props {
  group: TabsNode
  projectId: string
  /** Total number of tab groups in the whole layout, used to
   *  disable split actions when we're already at the cap. */
  totalGroups: number

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

  return (
    <div className="flex flex-col h-full min-h-0 bg-white dark:bg-gray-900">
      {/* Tab strip */}
      <div className="flex items-stretch h-9 bg-gray-100 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
        <div className="flex flex-1 min-w-0 overflow-x-auto">
          {group.tabs.map((tab) => {
            const isActive = tab.id === group.activeTabId
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => onActivateTab(group.id, tab.id)}
                onAuxClick={(e) => {
                  // Middle click closes the tab — terminal-style UX.
                  if (e.button === 1) {
                    e.preventDefault()
                    onCloseTab(group.id, tab.id)
                  }
                }}
                className={`group flex items-center gap-1.5 px-3 text-xs border-r border-gray-200 dark:border-gray-700 max-w-[14rem] flex-shrink-0 ${
                  isActive
                    ? 'bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100'
                    : 'text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700'
                }`}
                title={PANE_TYPE_LABELS[tab.paneType]}
              >
                <span className="truncate">
                  {PANE_TYPE_LABELS[tab.paneType]}
                </span>
                <span
                  role="button"
                  tabIndex={0}
                  onClick={(e) => {
                    e.stopPropagation()
                    onCloseTab(group.id, tab.id)
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.stopPropagation()
                      onCloseTab(group.id, tab.id)
                    }
                  }}
                  className="opacity-0 group-hover:opacity-100 hover:bg-gray-300 dark:hover:bg-gray-600 rounded p-0.5"
                  aria-label="Close tab"
                >
                  <X className="w-3 h-3" />
                </span>
              </button>
            )
          })}
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

      {/* Active pane body */}
      <PaneFrame
        key={activeTab.id}
        pane={activeTab}
        projectId={projectId}
        onConfigChange={onConfigChange}
      />
    </div>
  )
}

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
