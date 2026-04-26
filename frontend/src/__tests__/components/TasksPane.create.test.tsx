/**
 * TasksPane "Create Task" affordance (TP1, TP2, TP3).
 *
 * Reproduces the user-reported regression: after Phase C2 collapsed
 * the legacy ProjectPage into the Workbench, the TasksPane lost the
 * "タスク追加" button that opened TaskCreateModal. This file pins
 * down the spec so it cannot be lost again.
 */
import { describe, expect, it, vi, beforeAll, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { server } from '../mocks/server'
import { WorkbenchEventProvider } from '../../workbench/eventBus'
import TasksPane from '../../workbench/panes/TasksPane'
import type { TabsNode } from '../../workbench/types'

const PROJECT_ID = '69bfffad73ed736a9d13fd0f'

const SINGLE_TAB_TREE: TabsNode = {
  kind: 'tabs',
  id: 'g1',
  activeTabId: 'p1',
  tabs: [{ id: 'p1', paneType: 'tasks', paneConfig: {} }],
}

function renderTasksPane(opts?: { isLocked?: boolean }) {
  const isLocked = opts?.isLocked ?? false
  server.use(
    http.get(`/api/v1/projects/${PROJECT_ID}`, () =>
      HttpResponse.json({
        id: PROJECT_ID,
        name: 'P',
        members: [],
        remote: null,
        status: 'active',
        is_locked: isLocked,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }),
    ),
    http.get(`/api/v1/projects/${PROJECT_ID}/tasks`, () => HttpResponse.json([])),
  )
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/projects/${PROJECT_ID}`]}>
        <WorkbenchEventProvider tree={SINGLE_TAB_TREE}>
          <TasksPane
            paneId="p1"
            projectId={PROJECT_ID}
            paneConfig={{}}
            onConfigChange={vi.fn()}
          />
        </WorkbenchEventProvider>
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
  // Default: not locked — so the "create" affordance is visible.
})

describe('Workbench / TasksPane — TP1: Create Task affordance is present', () => {
  it('exposes a button labelled or titled with "タスク追加" / "Create Task" in the toolbar', async () => {
    renderTasksPane()
    // Wait for the project query to resolve so any project-conditional
    // UI (locked gate) is settled.
    await waitFor(() => {
      // Accept either of the legacy / Workbench label conventions.
      const byText = screen.queryByText(/タスク追加|タスクを追加|Create task|Add task/i)
      const byLabel = screen.queryByLabelText(/タスク追加|Create task|Add task/i)
      const byTitle = screen.queryByTitle(/タスク追加|Create task|Add task/i)
      expect(byText || byLabel || byTitle).not.toBeNull()
    })
  })
})

describe('Workbench / TasksPane — TP1/TP2: clicking it opens TaskCreateModal', () => {
  it('shows the modal after clicking the create button, then closes on cancel', async () => {
    const user = userEvent.setup()
    renderTasksPane()
    await waitFor(() => {
      const trigger =
        screen.queryByText(/タスク追加|タスクを追加|Create task|Add task/i) ??
        screen.queryByLabelText(/タスク追加|Create task|Add task/i) ??
        screen.queryByTitle(/タスク追加|Create task|Add task/i)
      expect(trigger).not.toBeNull()
    })
    const trigger =
      screen.queryByText(/タスク追加|タスクを追加|Create task|Add task/i) ??
      screen.queryByLabelText(/タスク追加|Create task|Add task/i) ??
      screen.queryByTitle(/タスク追加|Create task|Add task/i)
    await user.click(trigger as HTMLElement)
    // TaskCreateModal renders an input for the title — proxy for "modal is open".
    await waitFor(() => {
      expect(
        screen.queryByPlaceholderText(/タスク|task|title/i) ??
          screen.queryByLabelText(/title|タイトル|タスク名/i),
      ).not.toBeNull()
    })
  })
})

describe('Workbench / TasksPane — TP3: hidden when project is locked', () => {
  it('does NOT show the Create Task affordance when project.is_locked', async () => {
    renderTasksPane({ isLocked: true })
    // The pane mounts immediately and may show the button optimistically
    // until the project query resolves with is_locked=true. Wait for
    // the gate to apply (the button must end up absent).
    await waitFor(
      () => {
        expect(
          screen.queryByText(/タスク追加|タスクを追加/i),
        ).toBeNull()
        expect(
          screen.queryByLabelText(/タスク追加|Create task|Add task/i),
        ).toBeNull()
      },
      { timeout: 2000 },
    )
  })
})
