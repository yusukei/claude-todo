/**
 * TaskDetailPane invariants (TD1, TD2).
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import TaskDetailPane from '../../workbench/panes/TaskDetailPane'
import { WorkbenchEventProvider, useWorkbenchEventBus } from '../../workbench/eventBus'
import type { TabsNode } from '../../workbench/types'
import { server } from '../mocks/server'

const PROJECT_ID = '69bfffad73ed736a9d13fd0f'

const TREE: TabsNode = {
  kind: 'tabs',
  id: 'g1',
  activeTabId: 'p1',
  tabs: [{ id: 'p1', paneType: 'task-detail', paneConfig: {} }],
}

function renderPane(opts?: { taskId?: string; onConfigChange?: ReturnType<typeof vi.fn> }) {
  const onConfigChange = opts?.onConfigChange ?? vi.fn()
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  })
  // Default mocks for any task fetch the pane might attempt.
  server.use(
    http.get('/api/v1/projects/:projectId/tasks/:taskId', ({ params }) =>
      HttpResponse.json({
        id: params.taskId as string,
        title: 'Loaded task',
        status: 'todo',
        priority: 'medium',
        archived: false,
        comments: [],
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }),
    ),
    http.get('/api/v1/projects/:projectId/tasks', () => HttpResponse.json([])),
  )
  return {
    onConfigChange,
    ...render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <WorkbenchEventProvider tree={TREE}>
            <TaskDetailPane
              paneId="p1"
              projectId={PROJECT_ID}
              paneConfig={opts?.taskId ? { taskId: opts.taskId } : {}}
              onConfigChange={onConfigChange}
            />
          </WorkbenchEventProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  }
}

describe('Workbench / TaskDetailPane — TD1: empty state placeholder', () => {
  it('shows a placeholder when no taskId is in paneConfig', () => {
    renderPane()
    // The placeholder must hint the user how to populate the pane.
    // Accept either a generic "task" reference or a "click" hint.
    const text = document.body.textContent ?? ''
    const matched = /タスク|task|click|クリック|select|選択/i.test(text)
    expect(matched).toBe(true)
  })
})

describe('Workbench / TaskDetailPane — TD2: open-task subscription', () => {
  it('updates paneConfig.taskId when an open-task event fires on the bus', async () => {
    const onConfigChange = vi.fn()

    function Emitter() {
      const bus = useWorkbenchEventBus()
      return (
        <button
          type="button"
          data-testid="emit"
          onClick={() => bus.emit('open-task', { taskId: 'task-XYZ' })}
        >
          fire
        </button>
      )
    }

    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: 0 } },
    })
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <WorkbenchEventProvider tree={TREE}>
            <TaskDetailPane
              paneId="p1"
              projectId={PROJECT_ID}
              paneConfig={{}}
              onConfigChange={onConfigChange}
            />
            <Emitter />
          </WorkbenchEventProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    await act(async () => {
      ;(screen.getByTestId('emit') as HTMLButtonElement).click()
    })
    expect(onConfigChange).toHaveBeenCalledWith(
      expect.objectContaining({ taskId: 'task-XYZ' }),
    )
  })
})
