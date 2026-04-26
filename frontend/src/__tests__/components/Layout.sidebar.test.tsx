/**
 * Sidebar (Layout) navigation invariants (S1, S2, S3).
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Layout from '../../components/common/Layout'
import { useAuthStore } from '../../store/auth'
import { server } from '../mocks/server'
import { createMockUser, createMockProject } from '../mocks/factories'

const PROJECT = createMockProject({ id: 'proj-A', name: 'Alpha Project' })

beforeEach(() => {
  useAuthStore.setState({ user: createMockUser(), isInitialized: true })
  server.use(
    http.get('/api/v1/projects', () => HttpResponse.json([PROJECT])),
    http.get('/api/v1/projects/:projectId', () => HttpResponse.json(PROJECT)),
    http.get('/api/v1/tasks/live', () => HttpResponse.json([])),
    http.post('/api/v1/events/ticket', () => HttpResponse.json({ ticket: 'tkt' })),
  )
})

function renderLayout() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/projects']}>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/projects" element={<div data-testid="projects-page">PROJECTS</div>} />
            <Route path="/projects/:projectId" element={<div data-testid="project-page">P</div>} />
            <Route
              path="/projects/:projectId/settings"
              element={<div data-testid="project-settings">S</div>}
            />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Workbench / Sidebar — S1: project name links to /projects/:id', () => {
  it('renders the project name as a link to the project workspace', async () => {
    renderLayout()
    await waitFor(() => {
      const link = Array.from(document.querySelectorAll('a')).find(
        (a) => a.getAttribute('href') === '/projects/proj-A',
      )
      expect(link, 'expected a sidebar link to /projects/proj-A').toBeTruthy()
      expect(link!.textContent).toContain('Alpha Project')
    })
  })
})

describe('Workbench / Sidebar — S2: settings cog navigates to /projects/:id/settings', () => {
  it('renders a link to /projects/:id/settings next to each project', async () => {
    renderLayout()
    await waitFor(() => {
      const link = Array.from(document.querySelectorAll('a')).find(
        (a) => a.getAttribute('href') === '/projects/proj-A/settings',
      )
      expect(link, 'expected a sidebar settings link to /projects/proj-A/settings').toBeTruthy()
    })
  })
})

describe('Workbench / Sidebar — S3: global affordances are present', () => {
  it('exposes links to projects / bookmarks / knowledge / docsites', async () => {
    renderLayout()
    await waitFor(() => {
      const hrefs = Array.from(document.querySelectorAll('a')).map((a) => a.getAttribute('href'))
      expect(hrefs).toEqual(expect.arrayContaining(['/projects']))
      expect(hrefs.some((h) => h?.startsWith('/bookmarks'))).toBe(true)
      expect(hrefs.some((h) => h?.startsWith('/knowledge'))).toBe(true)
      expect(hrefs.some((h) => h?.startsWith('/docsites'))).toBe(true)
    })
  })
})
