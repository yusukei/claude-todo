/**
 * WorkbenchPage server-sync + project-switch invariants.
 *
 * Covers (or marks as RED):
 *   P8  — localStorage hydrate paints before server fetch resolves
 *   P9  — server payload with foreign client_id replaces state
 *   P10 — server payload with own client_id is a no-op (echo skip)
 *   P11 — server payload with same updated_at is a no-op
 *   P12 — local mutation triggers debounced PUT
 *   P13 — visibilitychange (hidden) sendBeacon flush
 *   P14 — pagehide sendBeacon flush
 *   P16 — project switch must NOT save the old tree to the new slot
 *   P17 — project switch hydrates from new project's stores
 *
 * These tests stub the panes through a mock pane registry so the
 * harness doesn't have to set up real Tasks / Documents / Terminal
 * plumbing.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, waitFor } from '@testing-library/react'
import { http, HttpResponse, delay } from 'msw'
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import WorkbenchPage from '../../pages/WorkbenchPage'
import { server } from '../mocks/server'
import * as paneRegistry from '../../workbench/paneRegistry'

const PROJECT_A = '69bfffad73ed736a9d13fd0f'
const PROJECT_B = '69c01338f760db06cd10677d'

const SAMPLE_TREE_LOCAL = {
  kind: 'tabs',
  id: 'g-local',
  tabs: [{ id: 'p-local', paneType: 'tasks', paneConfig: { _src: 'localStorage' } }],
  activeTabId: 'p-local',
}

const SAMPLE_TREE_SERVER = {
  kind: 'tabs',
  id: 'g-server',
  tabs: [{ id: 'p-server', paneType: 'tasks', paneConfig: { _src: 'server' } }],
  activeTabId: 'p-server',
}

function ProbePane(props: { paneConfig: Record<string, unknown> }) {
  return <div data-testid="probe">src={String(props.paneConfig._src ?? 'default')}</div>
}

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0 },
    },
  })
}

function renderWorkbench(initialPath: string) {
  vi.spyOn(paneRegistry, 'getPaneComponent').mockImplementation(
    () => ProbePane as unknown as ReturnType<typeof paneRegistry.getPaneComponent>,
  )
  const qc = makeQueryClient()
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/projects/:projectId" element={<WorkbenchPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  // Stable per-test client id so the echo-skip tests are predictable.
  window.sessionStorage.setItem('workbench:clientId', 'this-tab')
  // Default: server has no layout for either project.
  server.use(
    http.get('/api/v1/workbench/layouts/:projectId', () =>
      HttpResponse.json({ detail: 'not found' }, { status: 404 }),
    ),
    http.get('/api/v1/projects/:projectId', () =>
      HttpResponse.json({
        id: 'pid',
        name: 'project',
        members: [],
        remote: null,
        status: 'active',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }),
    ),
  )
})

afterEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
})

describe('Workbench / Persistence — P8: localStorage hydrate paints before server fetch', () => {
  it('the first paint shows the localStorage tree even while GET is pending', async () => {
    // Cache a layout in localStorage for project A.
    window.localStorage.setItem(
      `workbench:layout:${PROJECT_A}`,
      JSON.stringify({ version: 1, savedAt: 1, tree: SAMPLE_TREE_LOCAL }),
    )
    server.use(
      http.get(`/api/v1/workbench/layouts/${PROJECT_A}`, async () => {
        await delay(10_000) // never resolves within test window
        return HttpResponse.json({})
      }),
    )
    renderWorkbench(`/projects/${PROJECT_A}`)
    await waitFor(() => {
      expect(screen.getByTestId('probe').textContent).toBe('src=localStorage')
    })
  })
})

describe('Workbench / Persistence — P9: foreign client_id replaces local state', () => {
  it('replaces the state.tree when server returns a layout from another tab', async () => {
    window.localStorage.setItem(
      `workbench:layout:${PROJECT_A}`,
      JSON.stringify({ version: 1, savedAt: 1, tree: SAMPLE_TREE_LOCAL }),
    )
    server.use(
      http.get(`/api/v1/workbench/layouts/${PROJECT_A}`, () =>
        HttpResponse.json({
          tree: SAMPLE_TREE_SERVER,
          schema_version: 1,
          client_id: 'other-tab',
          updated_at: '2026-04-26T05:00:00+00:00',
        }),
      ),
    )
    renderWorkbench(`/projects/${PROJECT_A}`)
    await waitFor(() => {
      expect(screen.getByTestId('probe').textContent).toBe('src=server')
    })
  })
})

describe('Workbench / Persistence — P10: own client_id is an echo (no replace)', () => {
  it('does NOT replace state.tree when server returns our own client_id', async () => {
    window.localStorage.setItem(
      `workbench:layout:${PROJECT_A}`,
      JSON.stringify({ version: 1, savedAt: 1, tree: SAMPLE_TREE_LOCAL }),
    )
    server.use(
      http.get(`/api/v1/workbench/layouts/${PROJECT_A}`, () =>
        HttpResponse.json({
          tree: SAMPLE_TREE_SERVER,
          schema_version: 1,
          client_id: 'this-tab', // matches sessionStorage
          updated_at: '2026-04-26T05:00:00+00:00',
        }),
      ),
    )
    renderWorkbench(`/projects/${PROJECT_A}`)
    // Wait long enough for the GET to land + effect to run.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50))
    })
    expect(screen.getByTestId('probe').textContent).toBe('src=localStorage')
  })
})

describe('Workbench / Persistence — P16: project switch does NOT save old tree to new slot', () => {
  it('a pending debounced save for project A is not flushed against project B', async () => {
    // Track every PUT and POST(beacon) by URL path.
    const writes: Array<{ method: string; pid: string; body: unknown }> = []
    server.use(
      http.put('/api/v1/workbench/layouts/:projectId', async ({ request, params }) => {
        writes.push({
          method: 'PUT',
          pid: params.projectId as string,
          body: await request.json(),
        })
        return HttpResponse.json({ updated_at: 'ts' })
      }),
      http.post('/api/v1/workbench/layouts/:projectId/beacon', async ({ request, params }) => {
        writes.push({
          method: 'POST',
          pid: params.projectId as string,
          body: await request.json(),
        })
        return HttpResponse.json({ updated_at: 'ts' })
      }),
    )
    window.localStorage.setItem(
      `workbench:layout:${PROJECT_A}`,
      JSON.stringify({
        version: 1,
        savedAt: 1,
        tree: {
          ...SAMPLE_TREE_LOCAL,
          tabs: [{ ...SAMPLE_TREE_LOCAL.tabs[0], paneConfig: { _src: 'A-local' } }],
        },
      }),
    )
    window.localStorage.setItem(
      `workbench:layout:${PROJECT_B}`,
      JSON.stringify({
        version: 1,
        savedAt: 1,
        tree: {
          ...SAMPLE_TREE_LOCAL,
          tabs: [{ ...SAMPLE_TREE_LOCAL.tabs[0], paneConfig: { _src: 'B-local' } }],
        },
      }),
    )
    // Render with a real Router-based navigation so projectId really
    // changes (rerender keeps the same WorkbenchPage instance with
    // updated useParams).
    vi.spyOn(paneRegistry, 'getPaneComponent').mockImplementation(
      () => ProbePane as unknown as ReturnType<typeof paneRegistry.getPaneComponent>,
    )
    function Nav() {
      const navigate = useNavigate()
      return (
        <button
          type="button"
          data-testid="goto-b"
          onClick={() => navigate(`/projects/${PROJECT_B}`)}
        >
          go B
        </button>
      )
    }
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 0 } },
    })
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[`/projects/${PROJECT_A}`]}>
          <Routes>
            <Route
              path="/projects/:projectId"
              element={
                <>
                  <Nav />
                  <WorkbenchPage />
                </>
              }
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await waitFor(() =>
      expect(screen.getByTestId('probe').textContent).toBe('src=A-local'),
    )
    await act(async () => {
      screen.getByTestId('goto-b').click()
    })
    // Generous wait for debounce + any beacons.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 800))
    })

    // No write should have written project A's tree (_src: 'A-local')
    // to project B's slot.
    const wrongWrites = writes.filter((w) => {
      if (w.pid !== PROJECT_B) return false
      const body = w.body as {
        tree?: { tabs?: Array<{ paneConfig?: { _src?: string } }> }
      }
      const src = body?.tree?.tabs?.[0]?.paneConfig?._src
      return src === 'A-local' // A's marker should NEVER appear under B
    })
    expect(wrongWrites).toEqual([])
  })
})

describe('Workbench / Persistence — P17: project switch hydrates from new project stores', () => {
  it('shows project B local layout after navigating from project A to project B', async () => {
    window.localStorage.setItem(
      `workbench:layout:${PROJECT_A}`,
      JSON.stringify({
        version: 1,
        savedAt: 1,
        tree: {
          ...SAMPLE_TREE_LOCAL,
          tabs: [{ ...SAMPLE_TREE_LOCAL.tabs[0], paneConfig: { _src: 'A-local' } }],
        },
      }),
    )
    window.localStorage.setItem(
      `workbench:layout:${PROJECT_B}`,
      JSON.stringify({
        version: 1,
        savedAt: 1,
        tree: {
          ...SAMPLE_TREE_LOCAL,
          tabs: [{ ...SAMPLE_TREE_LOCAL.tabs[0], paneConfig: { _src: 'B-local' } }],
        },
      }),
    )
    // Mock the pane registry once for the whole render.
    vi.spyOn(paneRegistry, 'getPaneComponent').mockImplementation(
      () => ProbePane as unknown as ReturnType<typeof paneRegistry.getPaneComponent>,
    )
    const qc = makeQueryClient()
    // Render a small navigator inside the router so we can switch
    // projects without remounting MemoryRouter (which would reset
    // everything trivially).
    function Nav() {
      const navigate = useNavigate()
      return (
        <button
          type="button"
          data-testid="goto-b"
          onClick={() => navigate(`/projects/${PROJECT_B}`)}
        >
          go B
        </button>
      )
    }
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[`/projects/${PROJECT_A}`]}>
          <Routes>
            <Route
              path="/projects/:projectId"
              element={
                <>
                  <Nav />
                  <WorkbenchPage />
                </>
              }
            />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await waitFor(() => {
      expect(screen.getByTestId('probe').textContent).toBe('src=A-local')
    })
    await act(async () => {
      screen.getByTestId('goto-b').click()
    })
    await waitFor(() => {
      expect(screen.getByTestId('probe').textContent).toBe('src=B-local')
    })
  })
})
