import { describe, it, expect } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import ProjectsPage from '../../pages/ProjectsPage'
import { server } from '../mocks/server'
import { mockProject } from '../mocks/handlers'

function renderProjectsPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ProjectsPage />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('ProjectsPage', () => {
  it('APIレスポンスからプロジェクトカードを描画する', async () => {
    const projects = [
      { ...mockProject, id: 'p1', name: 'Project Alpha', description: 'Alpha desc' },
      { ...mockProject, id: 'p2', name: 'Project Beta', description: 'Beta desc' },
    ]
    server.use(
      http.get('/api/v1/projects', () => HttpResponse.json(projects))
    )

    renderProjectsPage()

    await waitFor(() => {
      expect(screen.getByText('Project Alpha')).toBeInTheDocument()
    })
    expect(screen.getByText('Project Beta')).toBeInTheDocument()
    expect(screen.getByText('Alpha desc')).toBeInTheDocument()
    expect(screen.getByText('Beta desc')).toBeInTheDocument()
  })

  it('プロジェクトがない場合に空状態を表示する', async () => {
    server.use(
      http.get('/api/v1/projects', () => HttpResponse.json([]))
    )

    renderProjectsPage()

    await waitFor(() => {
      expect(screen.getByText('プロジェクトがありません')).toBeInTheDocument()
    })
  })

  it('プロジェクトカードに正しいリンクが設定されている', async () => {
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json([
          { ...mockProject, id: 'proj-123', name: 'Link Test Project' },
        ])
      )
    )

    renderProjectsPage()

    await waitFor(() => {
      expect(screen.getByText('Link Test Project')).toBeInTheDocument()
    })

    const link = screen.getByText('Link Test Project').closest('a')
    expect(link).toHaveAttribute('href', '/projects/proj-123')
  })

  it('メンバー数を表示する', async () => {
    server.use(
      http.get('/api/v1/projects', () =>
        HttpResponse.json([mockProject])
      )
    )

    renderProjectsPage()

    await waitFor(() => {
      expect(screen.getByText('メンバー 1人')).toBeInTheDocument()
    })
  })
})
