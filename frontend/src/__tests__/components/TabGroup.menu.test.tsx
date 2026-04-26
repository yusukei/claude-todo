/**
 * TabGroup menu open/close + + (Add tab) dropdown.
 *
 * History: M4-M6 originally tested the "Change type" submenu in the
 * ⋮ menu. That UI was removed in task 69edb607 in favour of the +
 * (Add tab) dropdown — picking a pane type at add time covers the
 * same need without the hover-bridge submenu pitfalls. The replaced
 * tests verify the new + dropdown.
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DndContext } from '@dnd-kit/core'
import TabGroup from '../../workbench/TabGroup'
import { WorkbenchEventProvider } from '../../workbench/eventBus'
import type { TabsNode } from '../../workbench/types'

function makeGroup(): TabsNode {
  return {
    kind: 'tabs',
    id: 'g1',
    activeTabId: 'p1',
    tabs: [{ id: 'p1', paneType: 'tasks', paneConfig: {} }],
  }
}

function renderTabGroup(overrides?: {
  onAddTab?: (groupId: string, paneType: string) => void
}) {
  const noop = vi.fn()
  const onAddTab = overrides?.onAddTab ?? vi.fn()
  const group = makeGroup()
  render(
    <DndContext>
      <WorkbenchEventProvider tree={group}>
        <TabGroup
          group={group}
          projectId="proj-x"
          totalGroups={1}
          reducedMotion={false}
          onActivateTab={noop}
          onCloseTab={noop}
          onAddTab={onAddTab}
          onConfigChange={noop}
          onSplit={noop}
          onCloseGroup={noop}
        />
      </WorkbenchEventProvider>
    </DndContext>,
  )
  return { onAddTab }
}

describe('Workbench / TabGroup menu — M1: open on MoreVertical click', () => {
  it('shows the menu after clicking the pane menu button', async () => {
    const user = userEvent.setup()
    renderTabGroup()
    expect(screen.queryByText('Split right')).toBeNull()
    await user.click(screen.getByLabelText('Pane menu'))
    expect(screen.getByText('Split right')).toBeInTheDocument()
  })
})

describe('Workbench / TabGroup menu — M2: outside click closes', () => {
  it('closes the menu when the user mousedowns outside it', async () => {
    const user = userEvent.setup()
    renderTabGroup()
    await user.click(screen.getByLabelText('Pane menu'))
    expect(screen.getByText('Split right')).toBeInTheDocument()
    fireEvent.mouseDown(document.body)
    expect(screen.queryByText('Split right')).toBeNull()
  })
})

describe('Workbench / TabGroup menu — M3: ESC closes', () => {
  it('closes when ESC is pressed', async () => {
    const user = userEvent.setup()
    renderTabGroup()
    await user.click(screen.getByLabelText('Pane menu'))
    expect(screen.getByText('Split right')).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByText('Split right')).toBeNull()
  })
})

describe('Workbench / TabGroup menu — M4: ⋮ menu has no "Change type" entry', () => {
  it('does not render Change type in the pane menu', async () => {
    const user = userEvent.setup()
    renderTabGroup()
    await user.click(screen.getByLabelText('Pane menu'))
    expect(screen.queryByText(/Change type/i)).toBeNull()
  })
})

describe('Workbench / TabGroup + (Add tab) — M5: clicking + opens the type picker', () => {
  it('shows the type picker menu with all selectable pane types', async () => {
    const user = userEvent.setup()
    renderTabGroup()
    expect(screen.queryByRole('menu', { name: 'Add tab type' })).toBeNull()
    await user.click(screen.getByLabelText('Add tab'))
    const menu = await screen.findByRole('menu', { name: 'Add tab type' })
    // Each SELECTABLE_TYPE label is rendered as a menuitem button.
    expect(menu).toBeInTheDocument()
    // Spot-check a few labels are present.
    expect(screen.getByRole('menuitem', { name: 'Tasks' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Terminal' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Files' })).toBeInTheDocument()
  })
})

describe('Workbench / TabGroup + (Add tab) — M6: selecting a type calls onAddTab with that type', () => {
  it('clicking Terminal in the type picker calls onAddTab(group, "terminal") and closes the menu', async () => {
    const user = userEvent.setup()
    const { onAddTab } = renderTabGroup()
    await user.click(screen.getByLabelText('Add tab'))
    const terminalItem = await screen.findByRole('menuitem', { name: 'Terminal' })
    await user.click(terminalItem)
    expect(onAddTab).toHaveBeenCalledWith('g1', 'terminal')
    // Menu closes on selection.
    expect(screen.queryByRole('menu', { name: 'Add tab type' })).toBeNull()
  })
})

describe('Workbench / TabGroup + (Add tab) — M7: ESC closes the type picker', () => {
  it('pressing ESC after opening + closes the type picker', async () => {
    const user = userEvent.setup()
    renderTabGroup()
    await user.click(screen.getByLabelText('Add tab'))
    expect(screen.getByRole('menu', { name: 'Add tab type' })).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('menu', { name: 'Add tab type' })).toBeNull()
  })
})
