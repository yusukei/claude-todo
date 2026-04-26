/**
 * Smoke tests for the simpler top-level pages:
 *   - DocSitesPage    list render + empty state
 *   - DocumentPage    header back link + project name
 *   - NotFoundPage    404 + home link
 *   - SettingsPage    profile + ApiKeys section
 *   - BookmarksPage   common-project resolve / error fallback
 */
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import DocSitesPage from '../../pages/DocSitesPage'
import DocumentPage from '../../pages/DocumentPage'
import NotFoundPage from '../../pages/NotFoundPage'
import SettingsPage from '../../pages/SettingsPage'
import BookmarksPage from '../../pages/BookmarksPage'
import { server } from '../mocks/server'
import { useAuthStore } from '../../store/auth'
import { createMockUser } from '../mocks/factories'
import { renderWithProviders } from '../utils/renderWithProviders'

beforeEach(() => {
  useAuthStore.setState({ user: createMockUser(), isInitialized: true })
})

// Heavy children we don't need to exercise here.
vi.mock('../../components/project/ProjectDocumentsTab', () => ({
  default: () => <div data-testid="docs-tab" />,
}))
vi.mock('../../components/project/ProjectBookmarksTab', () => ({
  default: () => <div data-testid="bookmarks-tab" />,
}))
vi.mock('../../components/settings/ApiKeysSection', () => ({
  default: () => <div data-testid="api-keys-section">API keys</div>,
}))
vi.mock('../../pages/admin/PasskeysTab', () => ({
  default: () => <div data-testid="passkeys-tab" />,
}))

// ── DocSitesPage ───────────────────────────────────────────

describe('DocSitesPage — list / empty', () => {
  it('shows the empty hint when no sites exist', async () => {
    server.use(http.get('/api/v1/docsites', () => HttpResponse.json([])))
    renderWithProviders(<DocSitesPage />)
    await waitFor(() => {
      expect(screen.queryByText(/ドキュメントサイトがありません/)).not.toBeNull()
    })
  })

  it('renders one card per site', async () => {
    server.use(
      http.get('/api/v1/docsites', () =>
        HttpResponse.json([
          { id: 's1', name: 'Site A', description: 'A desc', page_count: 12 },
          { id: 's2', name: 'Site B', description: '', page_count: 3 },
        ]),
      ),
    )
    renderWithProviders(<DocSitesPage />)
    await waitFor(() => {
      expect(screen.queryByText('Site A')).not.toBeNull()
      expect(screen.queryByText('Site B')).not.toBeNull()
    })
    // Each card is a link to the viewer.
    const links = Array.from(document.querySelectorAll('a'))
    expect(links.some((a) => a.getAttribute('href') === '/docsites/s1')).toBe(true)
    expect(links.some((a) => a.getAttribute('href') === '/docsites/s2')).toBe(true)
  })
})

// ── DocumentPage ───────────────────────────────────────────

describe('DocumentPage — header shows project name + back link', () => {
  it('renders the project name from the project query', async () => {
    server.use(
      http.get('/api/v1/projects/p-x', () =>
        HttpResponse.json({ id: 'p-x', name: 'Pinned Project', color: '#abc' }),
      ),
    )
    renderWithProviders(<DocumentPage />, {
      route: '/projects/p-x/documents/d-y',
      path: '/projects/:projectId/documents/:documentId',
    })
    await waitFor(() => {
      expect(screen.queryByText('Pinned Project')).not.toBeNull()
    })
  })
})

// ── NotFoundPage ───────────────────────────────────────────

describe('NotFoundPage', () => {
  it('shows the 404 heading + home link', () => {
    renderWithProviders(<NotFoundPage />)
    expect(screen.getByText('404')).toBeInTheDocument()
    const home = screen.getByText('ホームに戻る')
    expect(home.getAttribute('href')).toBe('/')
  })
})

// ── SettingsPage ───────────────────────────────────────────

describe('SettingsPage — profile + sections', () => {
  it('shows the user profile and renders the ApiKeysSection', () => {
    useAuthStore.setState({
      user: createMockUser({ name: 'Alice', email: 'alice@x', auth_type: 'google' }),
      isInitialized: true,
    })
    renderWithProviders(<SettingsPage />)
    expect(screen.getByText('Alice')).toBeInTheDocument()
    expect(screen.getByText('alice@x')).toBeInTheDocument()
    expect(screen.getByTestId('api-keys-section')).toBeInTheDocument()
  })

  it('only shows the Passkeys section for local (admin auth_type) users', () => {
    useAuthStore.setState({
      user: createMockUser({ name: 'Local Admin', auth_type: 'admin' }),
      isInitialized: true,
    })
    renderWithProviders(<SettingsPage />)
    expect(screen.getByTestId('passkeys-tab')).toBeInTheDocument()
  })

  it('hides the Passkeys section for Google-auth users', () => {
    useAuthStore.setState({
      user: createMockUser({ name: 'Google User', auth_type: 'google' }),
      isInitialized: true,
    })
    renderWithProviders(<SettingsPage />)
    expect(screen.queryByTestId('passkeys-tab')).toBeNull()
  })
})

// ── BookmarksPage ──────────────────────────────────────────

describe('BookmarksPage — common-project resolution', () => {
  it('renders the bookmarks tab once the common project resolves', async () => {
    server.use(
      http.get('/api/v1/projects/common', () =>
        HttpResponse.json({ id: 'common-id', name: 'Common', hidden: true }),
      ),
    )
    renderWithProviders(<BookmarksPage />, {
      route: '/bookmarks',
      path: '/bookmarks',
    })
    await waitFor(() => {
      expect(screen.queryByTestId('bookmarks-tab')).not.toBeNull()
    })
  })

  it('shows the unset-project fallback if common-project lookup fails', async () => {
    server.use(
      http.get('/api/v1/projects/common', () =>
        HttpResponse.json({ detail: 'not found' }, { status: 404 }),
      ),
    )
    renderWithProviders(<BookmarksPage />)
    await waitFor(() => {
      expect(
        screen.queryByText(/Common プロジェクトが未設定/),
      ).not.toBeNull()
    })
  })
})
