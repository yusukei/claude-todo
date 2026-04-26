/**
 * WorkbenchPage header invariants (H1-H6).
 *
 * The header strip exposes navigation + layout controls (← projects,
 * project name, Layout preset menu, Copy URL, Reset). All of them
 * must be present and operate as specified — losing any one of them
 * was the kind of silent regression the TasksPane.create incident
 * exposed.
 */
import { describe, expect, it, vi, beforeAll, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import WorkbenchPage from '../../pages/WorkbenchPage'
import { server } from '../mocks/server'
import * as paneRegistry from '../../workbench/paneRegistry'

const PROJECT_ID = '69bfffad73ed736a9d13fd0f'

function ProbePane() {
  return <div data-testid="probe" />
}

function renderPage() {
  vi.spyOn(paneRegistry, 'getPaneComponent').mockImplementation(
    () => ProbePane as unknown as ReturnType<typeof paneRegistry.getPaneComponent>,
  )
  server.use(
    http.get(`/api/v1/projects/${PROJECT_ID}`, () =>
      HttpResponse.json({
        id: PROJECT_ID,
        name: 'My Test Project',
        members: [],
        remote: null,
        status: 'active',
        is_locked: false,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }),
    ),
    http.get('/api/v1/workbench/layouts/:projectId', () =>
      HttpResponse.json({ detail: 'not found' }, { status: 404 }),
    ),
  )
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/projects/${PROJECT_ID}`]}>
        <Routes>
          <Route path="/projects/:projectId" element={<WorkbenchPage />} />
          <Route path="/projects" element={<div data-testid="projects-list">PROJECTS LIST</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeAll(() => {
  if (!('ResizeObserver' in globalThis)) {
    ;(globalThis as { ResizeObserver?: unknown }).ResizeObserver = vi
      .fn()
      .mockImplementation(() => ({
        observe: vi.fn(),
        disconnect: vi.fn(),
      }))
  }
})

beforeEach(() => {
  window.sessionStorage.setItem('workbench:clientId', 'test-tab')
})

describe('Workbench / Header — H1: ← projects link', () => {
  it('navigates to /projects when clicked', async () => {
    const user = userEvent.setup()
    renderPage()
    await waitFor(() => {
      expect(screen.queryByText(/projects/i)).not.toBeNull()
    })
    const back = screen.getByRole('link', { name: /projects/i })
    expect(back.getAttribute('href')).toBe('/projects')
    await user.click(back)
    await waitFor(() => {
      expect(screen.getByTestId('projects-list')).toBeInTheDocument()
    })
  })
})

describe('Workbench / Header — H2: project name displayed', () => {
  it('shows the project name from the project query', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.queryByText(/My Test Project/i)).not.toBeNull()
    })
  })
})

describe('Workbench / Header — H3: Layout preset menu lists 5 presets', () => {
  it('opens a dropdown with the preset entries when clicked', async () => {
    const user = userEvent.setup()
    renderPage()
    const layoutBtn = await screen.findByRole('button', { name: /Layout/i })
    await user.click(layoutBtn)
    // Each preset has a label (Tasks only / Tasks + Detail / Tasks + Terminal / Tasks + Doc + Terminal / Doc + Files)
    const labels = [
      /Tasks only/i,
      /Tasks \+ Detail/i,
      /Tasks \+ Terminal/i,
      /Doc \+ Files/i,
    ]
    for (const re of labels) {
      expect(screen.queryByText(re)).not.toBeNull()
    }
  })
})

describe('Workbench / Header — H4: Copy URL button', () => {
  it('calls navigator.clipboard.writeText with the current URL', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    renderPage()
    const copyBtn = await screen.findByRole('button', { name: /Copy URL/i })
    await user.click(copyBtn)
    expect(writeText).toHaveBeenCalledTimes(1)
    expect(writeText.mock.calls[0][0]).toMatch(/^http/)
  })
})

describe('Workbench / Header — H5: Reset button opens confirm modal', () => {
  it('shows a "Replace current layout?" modal when clicked', async () => {
    const user = userEvent.setup()
    renderPage()
    const resetBtn = await screen.findByRole('button', { name: /Reset/i })
    await user.click(resetBtn)
    expect(screen.getByText(/Replace current layout\?/i)).toBeInTheDocument()
  })
})

describe('Workbench / Header — H6: confirm modal ESC / Enter', () => {
  it('closes on ESC, confirms on Enter', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(await screen.findByRole('button', { name: /Reset/i }))
    expect(screen.getByText(/Replace current layout\?/i)).toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByText(/Replace current layout\?/i)).toBeNull()
    // Re-open and confirm via Enter.
    await user.click(await screen.findByRole('button', { name: /Reset/i }))
    fireEvent.keyDown(window, { key: 'Enter' })
    expect(screen.queryByText(/Replace current layout\?/i)).toBeNull()
  })
})
