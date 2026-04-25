import { Fragment } from 'react'
import { Group, Panel, Separator, type Layout } from 'react-resizable-panels'
import type { LayoutTree, PaneType } from './types'
import TabGroup from './TabGroup'
import { countTabGroups } from './treeUtils'

interface Props {
  tree: LayoutTree
  projectId: string

  onActivateTab: (groupId: string, tabId: string) => void
  onCloseTab: (groupId: string, tabId: string) => void
  onAddTab: (groupId: string, paneType: PaneType) => void
  onChangePaneType: (paneId: string, paneType: PaneType) => void
  onConfigChange: (paneId: string, patch: Record<string, unknown>) => void
  onSplit: (groupId: string, orientation: 'horizontal' | 'vertical') => void
  onCloseGroup: (groupId: string) => void
  onSplitSizes: (splitId: string, sizes: number[]) => void
}

/**
 * Recursively render a LayoutTree using react-resizable-panels v4
 * (``Group`` / ``Panel`` / ``Separator``). Tracks the total tab-
 * group count at the top so each TabGroup can disable its split
 * actions when the layout has hit ``MAX_TAB_GROUPS``.
 */
export default function WorkbenchLayout(props: Props) {
  const total = countTabGroups(props.tree)
  return <Renderer {...props} totalGroups={total} />
}

interface RendererProps extends Props {
  totalGroups: number
}

function Renderer({
  tree,
  projectId,
  totalGroups,
  onActivateTab,
  onCloseTab,
  onAddTab,
  onChangePaneType,
  onConfigChange,
  onSplit,
  onCloseGroup,
  onSplitSizes,
}: RendererProps) {
  if (tree.kind === 'tabs') {
    return (
      <TabGroup
        group={tree}
        projectId={projectId}
        totalGroups={totalGroups}
        onActivateTab={onActivateTab}
        onCloseTab={onCloseTab}
        onAddTab={onAddTab}
        onChangePaneType={onChangePaneType}
        onConfigChange={onConfigChange}
        onSplit={onSplit}
        onCloseGroup={onCloseGroup}
      />
    )
  }
  // Split node — recurse.
  const childIds = tree.children.map((c) => c.id)
  return (
    <Group
      orientation={tree.orientation}
      id={tree.id}
      onLayoutChanged={(layout: Layout) => {
        const sizes = childIds.map((id) => layout[id] ?? 0)
        if (sizes.every((s) => s > 0)) {
          onSplitSizes(tree.id, sizes)
        }
      }}
      style={{ display: 'flex', flexDirection: tree.orientation === 'horizontal' ? 'row' : 'column', height: '100%', width: '100%' }}
    >
      {tree.children.map((child, i) => (
        <Fragment key={child.id}>
          {i > 0 && (
            <Separator
              className={
                tree.orientation === 'horizontal'
                  ? 'w-1 bg-gray-200 dark:bg-gray-700 hover:bg-blue-400 transition-colors cursor-col-resize'
                  : 'h-1 bg-gray-200 dark:bg-gray-700 hover:bg-blue-400 transition-colors cursor-row-resize'
              }
            />
          )}
          <Panel
            id={child.id}
            defaultSize={tree.sizes[i]}
            minSize={10}
          >
            <Renderer
              tree={child}
              projectId={projectId}
              totalGroups={totalGroups}
              onActivateTab={onActivateTab}
              onCloseTab={onCloseTab}
              onAddTab={onAddTab}
              onChangePaneType={onChangePaneType}
              onConfigChange={onConfigChange}
              onSplit={onSplit}
              onCloseGroup={onCloseGroup}
              onSplitSizes={onSplitSizes}
            />
          </Panel>
        </Fragment>
      ))}
    </Group>
  )
}
