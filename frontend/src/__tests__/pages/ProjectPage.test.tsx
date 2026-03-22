import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import ProjectPage from '../../pages/ProjectPage'
import { server } from '../mocks/server'
import { mockProject, mockTask } from '../mocks/handlers'

function renderProjectPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/projects/project-id-1']}>
        <Routes>
          <Route path="/projects/:projectId" element={<ProjectPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('ProjectPage', () => {
  it('プロジェクトヘッダーにプロジェクト名を表示する', async () => {
    renderProjectPage()

    await waitFor(() => {
      expect(screen.getByText('Test Project')).toBeInTheDocument()
    })
  })

  it('ボードビューとリストビューを切り替えられる', async () => {
    renderProjectPage()

    await waitFor(() => {
      expect(screen.getByText('Test Project')).toBeInTheDocument()
    })

    // デフォルトはボードビュー。リストボタンをクリック
    const listButton = screen.getByTitle('リスト')
    await userEvent.click(listButton)

    // リストビューではタスクがリスト表示される
    // TaskList コンポーネントが描画される（タスクタイトルが表示される）
    await waitFor(() => {
      expect(screen.getByText('Test Task')).toBeInTheDocument()
    })

    // ボードビューに戻す
    const boardButton = screen.getByTitle('カンバン')
    await userEvent.click(boardButton)

    // ボードビューでもタスクが表示される
    await waitFor(() => {
      expect(screen.getByText('Test Task')).toBeInTheDocument()
    })
  })

  it('「タスク追加」ボタンで作成モーダルが開く', async () => {
    renderProjectPage()

    await waitFor(() => {
      expect(screen.getByText('Test Project')).toBeInTheDocument()
    })

    await userEvent.click(screen.getByText('タスク追加'))

    // TaskCreateModal が表示される
    await waitFor(() => {
      expect(screen.getByText('タスクを作成')).toBeInTheDocument()
    })
  })

  it('カスタムプロジェクトデータを正しく表示する', async () => {
    const customProject = {
      ...mockProject,
      name: 'Custom Project Name',
      color: '#ff0000',
    }
    server.use(
      http.get('/api/v1/projects/:projectId', () => HttpResponse.json(customProject))
    )

    renderProjectPage()

    await waitFor(() => {
      expect(screen.getByText('Custom Project Name')).toBeInTheDocument()
    })
  })

  it('タスクがない場合リストビューで空状態を表示する', async () => {
    server.use(
      http.get('/api/v1/projects/:projectId/tasks', () => HttpResponse.json([]))
    )

    renderProjectPage()

    await waitFor(() => {
      expect(screen.getByText('Test Project')).toBeInTheDocument()
    })

    // リストビューに切り替え
    await userEvent.click(screen.getByTitle('リスト'))

    await waitFor(() => {
      expect(screen.getByText('タスクがありません')).toBeInTheDocument()
    })
  })
})
