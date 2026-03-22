import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import TaskList from '../../components/task/TaskList'
import type { Task } from '../../types'

const baseTasks: Task[] = [
  {
    id: 'task-1',
    project_id: 'project-1',
    title: 'First Task',
    description: null,
    status: 'todo',
    priority: 'medium',
    due_date: null,
    assignee_id: null,
    parent_task_id: null,
    tags: [],
    comments: [],
    is_deleted: false,
    completed_at: null,
    needs_detail: false,
    approved: false,
    created_by: 'user-1',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    sort_order: 0,
  },
  {
    id: 'task-2',
    project_id: 'project-1',
    title: 'Second Task',
    description: null,
    status: 'in_progress',
    priority: 'high',
    due_date: null,
    assignee_id: null,
    parent_task_id: null,
    tags: [],
    comments: [],
    is_deleted: false,
    completed_at: null,
    needs_detail: false,
    approved: false,
    created_by: 'user-1',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    sort_order: 1,
  },
]

describe('TaskList', () => {
  it('タスクのタイトルを描画する', () => {
    render(<TaskList tasks={baseTasks} projectId="project-1" onTaskClick={() => {}} onUpdateFlags={() => {}} />)
    expect(screen.getByText('First Task')).toBeInTheDocument()
    expect(screen.getByText('Second Task')).toBeInTheDocument()
  })

  it('タスクがない場合に空状態メッセージを表示する', () => {
    render(<TaskList tasks={[]} projectId="project-1" onTaskClick={() => {}} onUpdateFlags={() => {}} />)
    expect(screen.getByText('タスクがありません')).toBeInTheDocument()
  })

  it('タスク行クリック時に onTaskClick が呼ばれる', async () => {
    const onTaskClick = vi.fn()
    render(<TaskList tasks={baseTasks} projectId="project-1" onTaskClick={onTaskClick} onUpdateFlags={() => {}} />)
    await userEvent.click(screen.getByText('First Task'))
    expect(onTaskClick).toHaveBeenCalledWith('task-1')
  })

  it('ステータスバッジが正しいラベルを表示する', () => {
    render(<TaskList tasks={baseTasks} projectId="project-1" onTaskClick={() => {}} onUpdateFlags={() => {}} />)
    expect(screen.getByText('TODO')).toBeInTheDocument()
    expect(screen.getByText('進行中')).toBeInTheDocument()
  })

  it('期限切れタスクに赤色スタイルが適用される', () => {
    const overdueTasks: Task[] = [
      {
        ...baseTasks[0],
        due_date: '2020-01-01T00:00:00Z',
        status: 'todo',
      },
    ]
    const { container } = render(
      <TaskList tasks={overdueTasks} projectId="project-1" onTaskClick={() => {}} onUpdateFlags={() => {}} />
    )
    expect(container.querySelector('.text-red-500')).toBeInTheDocument()
  })

  it('done のタスクは期限切れ表示にならない', () => {
    const doneTasks: Task[] = [
      {
        ...baseTasks[0],
        due_date: '2020-01-01T00:00:00Z',
        status: 'done',
      },
    ]
    const { container } = render(
      <TaskList tasks={doneTasks} projectId="project-1" onTaskClick={() => {}} onUpdateFlags={() => {}} />
    )
    expect(container.querySelector('.text-red-500')).not.toBeInTheDocument()
  })
})
