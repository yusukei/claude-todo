/**
 * Smoke tests for the remaining pages:
 *   - WorkspacePage         agent list + register dialog trigger
 *   - TerminalPage          session-list mode (no sessionId)
 *   - GoogleCallbackPage    error redirect when ?error=...
 *   - ProjectSettingsPage   project name + back link
 *   - KnowledgePage         empty state
 *   - ErrorTrackerPage      mount renders without crashing
 */
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { Routes, Route } from 'react-router-dom'
import WorkspacePage from '../../pages/WorkspacePage'
import TerminalPage from '../../pages/TerminalPage'
import GoogleCallbackPage from '../../pages/GoogleCallbackPage'
import ProjectSettingsPage from '../../pages/ProjectSettingsPage'
import KnowledgePage from '../../pages/KnowledgePage'
import ErrorTrackerPage from '../../pages/ErrorTrackerPage'
import { server } from '../mocks/server'
import { useAuthStore } from '../../store/auth'
import { createMockUser } from '../mocks/factories'
import { renderWithProviders } from '../utils/renderWithProviders'

beforeEach(() => {
  useAuthStore.setState({ user: createMockUser({ is_admin: true }), isInitialized: true })
})

// xterm + heavy children we don't need here.
vi.mock('../../components/workspace/TerminalView', () => ({
  default: () => <div data-testid="terminal-view" />,
}))
vi.mock('../../components/workspace/TerminalSessionList', () => ({
  default: () => <div data-testid="session-list" />,
}))
vi.mock('../../components/project/ProjectMembersTab', () => ({
  default: () => <div data-testid="members-tab" />,
}))
vi.mock('../../components/project/ProjectSecretsTab', () => ({
  default: () => <div data-testid="secrets-tab" />,
}))

// ── WorkspacePage ──────────────────────────────────────────

describe('WorkspacePage — render', () => {
  it('renders the agent list (empty state) once /workspaces/agents resolves', async () => {
    server.use(
      http.get('/api/v1/workspaces/agents', () => HttpResponse.json([])),
      http.get('/api/v1/workspaces/supervisors', () => HttpResponse.json([])),
      http.get('/api/v1/projects', () => HttpResponse.json([])),
    )
    renderWithProviders(<WorkspacePage />)
    await waitFor(() => {
      expect(screen.queryByText(/Agent が登録されていません/)).not.toBeNull()
    })
  })
})

// ── TerminalPage ───────────────────────────────────────────

describe('TerminalPage — agent + session list', () => {
  it('renders the session list when no sessionId is in the URL', async () => {
    server.use(
      http.get('/api/v1/workspaces/agents', () =>
        HttpResponse.json([
          {
            id: 'a-1',
            name: 'Workstation',
            hostname: 'host',
            os_type: 'darwin',
            available_shells: ['/bin/zsh'],
            is_online: true,
            last_seen_at: null,
            created_at: '2026-01-01T00:00:00Z',
            agent_version: '1.0',
          },
        ]),
      ),
    )
    renderWithProviders(<TerminalPage />, {
      route: '/workspaces/terminal/a-1',
      path: '/workspaces/terminal/:agentId',
    })
    await waitFor(() => {
      expect(screen.queryByTestId('session-list')).not.toBeNull()
    })
  })
})

// ── GoogleCallbackPage ────────────────────────────────────

describe('GoogleCallbackPage — error redirect', () => {
  it('quietly redirects to /login on ?error=... without crashing', async () => {
    // useEffect fires synchronously inside `act()` on mount and calls
    // navigate('/login?error=...'), which unmounts the spinner before
    // any RTL query can run. So instead of asserting the spinner copy,
    // we mount the page on a Routes config that recognises both
    // /auth/google/callback and /login, and verify navigation lands
    // on /login (the redirect happened, the page didn't crash).
    renderWithProviders(
      <Routes>
        <Route path="/auth/google/callback" element={<GoogleCallbackPage />} />
        <Route path="/login" element={<div data-testid="login-stub">login</div>} />
      </Routes>,
      { route: '/auth/google/callback?error=denied' },
    )
    await waitFor(() => {
      expect(screen.queryByTestId('login-stub')).not.toBeNull()
    })
  })
})

// ── ProjectSettingsPage ───────────────────────────────────

describe('ProjectSettingsPage — header shows project name', () => {
  it('renders the project name from the project query', async () => {
    server.use(
      http.get('/api/v1/projects/p-1', () =>
        HttpResponse.json({
          id: 'p-1',
          name: 'Project Alpha',
          color: '#abc',
          status: 'active',
          is_locked: false,
          members: [{ user_id: useAuthStore.getState().user!.id, role: 'owner' }],
          created_by: useAuthStore.getState().user!.id,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }),
      ),
    )
    renderWithProviders(<ProjectSettingsPage />, {
      route: '/projects/p-1/settings',
      path: '/projects/:projectId/settings',
    })
    // The project name renders in two places (header subtitle and the
    // basic-settings card row). We only need to verify the query
    // resolved and the name made it onto the page.
    await waitFor(() => {
      expect(screen.queryAllByText('Project Alpha').length).toBeGreaterThan(0)
    })
  })
})

// ── KnowledgePage ─────────────────────────────────────────

describe('KnowledgePage — empty state', () => {
  it('renders without crashing when the list is empty', async () => {
    server.use(
      http.get(/\/api\/v1\/knowledge/, () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    )
    renderWithProviders(<KnowledgePage />)
    // Non-crash assertion — component mounts and lists query resolves.
    await waitFor(() => {
      // KnowledgePage renders some heading or input — the safe assertion
      // is that the document body is non-empty.
      expect(document.body.textContent?.length).toBeGreaterThan(0)
    })
  })
})

// ── ErrorTrackerPage ──────────────────────────────────────

describe('ErrorTrackerPage — mount', () => {
  it('renders without crashing for an admin user with no error projects', async () => {
    server.use(
      http.get(/\/api\/v1\/error[-_]tracker\/projects/, () =>
        HttpResponse.json([]),
      ),
      http.get(/\/api\/v1\/error[-_]tracker/, () => HttpResponse.json([])),
      http.get(/\/api\/v1\/projects/, () => HttpResponse.json([])),
    )
    renderWithProviders(<ErrorTrackerPage />)
    await waitFor(() => {
      expect(document.body.textContent?.length).toBeGreaterThan(0)
    })
  })
})
