import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import TaskDetail from '../../components/task/TaskDetail'
import { server } from '../mocks/server'

const mockTaskDetail = {
  id: 'task-id-1',
  project_id: 'project-id-1',
  title: 'Detail Task',
  description: 'Task description text',
  status: 'todo',
  priority: 'high',
  due_date: '2030-12-31T00:00:00Z',
  assignee_id: null,
  parent_task_id: null,
  tags: ['bug'],
  comments: [
    {
      id: 'comment-1',
      content: 'This is a comment',
      author_id: 'user-1',
      author_name: 'Test User',
      created_at: '2024-06-15T10:00:00Z',
    },
  ],
  is_deleted: false,
  completed_at: null,
  created_by: 'user-1',
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
  sort_order: 0,
}

function renderTaskDetail(onClose = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  server.use(
    http.get('/api/v1/projects/:projectId/tasks/:taskId', () =>
      HttpResponse.json(mockTaskDetail)
    )
  )

  return {
    onClose,
    ...render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <TaskDetail taskId="task-id-1" projectId="project-id-1" onClose={onClose} />
        </MemoryRouter>
      </QueryClientProvider>
    ),
  }
}

describe('TaskDetail', () => {
  it('タスクの詳細を描画する (タイトル、説明、ステータス、コメント)', async () => {
    renderTaskDetail()

    await waitFor(() => {
      expect(screen.getByText('Detail Task')).toBeInTheDocument()
    })
    expect(screen.getByText('Task description text')).toBeInTheDocument()
    expect(screen.getByText('This is a comment')).toBeInTheDocument()
    expect(screen.getByText('Test User')).toBeInTheDocument()
    // ステータスボタンが表示されている
    expect(screen.getByText('TODO')).toBeInTheDocument()
    expect(screen.getByText('進行中')).toBeInTheDocument()
    expect(screen.getByText('完了')).toBeInTheDocument()
  })

  it('ステータスボタンクリックで mutation が発火する', async () => {
    let patchCalled = false
    server.use(
      http.patch('/api/v1/projects/:projectId/tasks/:taskId', () => {
        patchCalled = true
        return HttpResponse.json({ ...mockTaskDetail, status: 'in_progress' })
      })
    )

    renderTaskDetail()

    await waitFor(() => {
      expect(screen.getByText('Detail Task')).toBeInTheDocument()
    })

    await userEvent.click(screen.getByText('進行中'))

    await waitFor(() => {
      expect(patchCalled).toBe(true)
    })
  })

  it('Escape キーで詳細パネルが閉じる', async () => {
    const onClose = vi.fn()
    renderTaskDetail(onClose)

    await waitFor(() => {
      expect(screen.getByText('Detail Task')).toBeInTheDocument()
    })

    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('コメント数が表示される', async () => {
    renderTaskDetail()

    await waitFor(() => {
      expect(screen.getByText('コメント (1)')).toBeInTheDocument()
    })
  })
})
