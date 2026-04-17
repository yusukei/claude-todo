/**
 * TaskTimeline tests.
 *
 * JSDOM can't measure layout, so these tests exercise the structural parts
 * that work without a real layout engine: empty-state, bar rendering,
 * group header display, and the toolbar's group-by selector.
 */

import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TaskTimeline from '../../components/task/TaskTimeline'
import { createMockTask } from '../mocks/factories'
import { renderWithProviders } from '../utils/renderWithProviders'

// react-window depends on layout measurements we can't fake in JSDOM.
// Stub it to a pass-through that renders every row, so row-level assertions
// remain meaningful without the virtualization machinery.
vi.mock('react-window', () => ({
  FixedSizeList: ({ itemCount, itemData, children: Child }: any) => {
    const rows = []
    for (let i = 0; i < itemCount; i++) {
      rows.push(<Child key={i} index={i} style={{}} data={itemData} />)
    }
    return <div>{rows}</div>
  },
}))

// ResizeObserver doesn't exist in JSDOM — stub it.
class MockResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
// @ts-expect-error JSDOM global
globalThis.ResizeObserver = MockResizeObserver

const baseProps = {
  projectId: 'project-id-1',
  onTaskClick: vi.fn(),
}

describe('TaskTimeline', () => {
  it('shows an empty-state message when no tasks are provided', () => {
    renderWithProviders(<TaskTimeline tasks={[]} {...baseProps} />)
    expect(screen.getByText('タスクがありません')).toBeInTheDocument()
  })

  it('renders a row per task with a bar button', () => {
    const tasks = [
      createMockTask({ id: 't1', title: 'First task', status: 'todo' }),
      createMockTask({ id: 't2', title: 'Second task', status: 'in_progress' }),
    ]
    renderWithProviders(<TaskTimeline tasks={tasks} {...baseProps} />)

    expect(screen.getByText('First task')).toBeInTheDocument()
    expect(screen.getByText('Second task')).toBeInTheDocument()
    expect(screen.getByTestId('timeline-bar-t1')).toBeInTheDocument()
    expect(screen.getByTestId('timeline-bar-t2')).toBeInTheDocument()
  })

  it('renders group headers when grouping by priority', () => {
    const tasks = [
      createMockTask({ id: 't1', title: 'Urgent', priority: 'urgent' }),
      createMockTask({ id: 't2', title: 'Low', priority: 'low' }),
    ]
    renderWithProviders(
      <TaskTimeline tasks={tasks} {...baseProps} groupBy="priority" />,
    )
    expect(screen.getByText('緊急')).toBeInTheDocument()
    expect(screen.getByText('低')).toBeInTheDocument()
  })

  it('invokes onTaskClick when a bar is clicked', async () => {
    const onTaskClick = vi.fn()
    const tasks = [createMockTask({ id: 't1', title: 'Click me' })]
    renderWithProviders(
      <TaskTimeline tasks={tasks} {...baseProps} onTaskClick={onTaskClick} />,
    )
    const user = userEvent.setup()
    await user.click(screen.getByTestId('timeline-bar-t1'))
    expect(onTaskClick).toHaveBeenCalledWith('t1')
  })

  it('propagates group-by changes through the select control', async () => {
    const onGroupByChange = vi.fn()
    const tasks = [createMockTask({ id: 't1', title: 'Task' })]
    renderWithProviders(
      <TaskTimeline
        tasks={tasks}
        {...baseProps}
        groupBy="none"
        onGroupByChange={onGroupByChange}
      />,
    )
    const select = screen.getByRole('combobox') as HTMLSelectElement
    const user = userEvent.setup()
    await user.selectOptions(select, 'priority')
    expect(onGroupByChange).toHaveBeenCalledWith('priority')
  })
})
