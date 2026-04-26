/**
 * SSE → workbench layout invalidation (P15).
 *
 * When a `workbench.layout.updated` SSE event arrives, useSSE must
 * invalidate the React Query keyed `['workbench-layout', projectId]`
 * so WorkbenchPage's useQuery refetches and the cross-tab merge
 * effect runs.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { useSSE } from '../../hooks/useSSE'
import { useAuthStore } from '../../store/auth'
import { createMockUser } from '../mocks/factories'

vi.mock('../../api/client', () => ({
  api: {
    post: vi.fn().mockResolvedValue({ data: { ticket: 'tkt' } }),
  },
}))

class MockEventSource {
  static instances: MockEventSource[] = []
  url: string
  onmessage: ((e: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  readyState = 0
  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
  }
  close = vi.fn(() => {
    this.readyState = 2
  })
  simulate(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent)
  }
}

const originalEventSource = global.EventSource

beforeEach(() => {
  MockEventSource.instances = []
  ;(global as unknown as { EventSource: unknown }).EventSource = MockEventSource
  useAuthStore.setState({ user: createMockUser(), isInitialized: true })
})

afterEach(() => {
  ;(global as unknown as { EventSource: unknown }).EventSource = originalEventSource
})

describe('Workbench / Persistence — P15: SSE workbench.layout.updated invalidates query', () => {
  it('calls queryClient.invalidateQueries with ["workbench-layout", projectId]', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      createElement(QueryClientProvider, { client: qc }, children)

    renderHook(() => useSSE(), { wrapper })
    await waitFor(() => {
      expect(MockEventSource.instances.length).toBeGreaterThan(0)
    })

    act(() => {
      MockEventSource.instances[0].simulate({
        type: 'workbench.layout.updated',
        user_id: 'me',
        project_id: 'proj-abc',
        data: {
          project_id: 'proj-abc',
          client_id: 'tab-other',
          schema_version: 1,
          updated_at: '2026-04-26T05:00:00+00:00',
        },
        server_time: '2026-04-26T05:00:00+00:00',
      })
    })

    const layoutInvalidations = invalidateSpy.mock.calls.filter((args) => {
      const opt = args[0] as { queryKey?: unknown[] } | undefined
      const k = opt?.queryKey
      return Array.isArray(k) && k[0] === 'workbench-layout' && k[1] === 'proj-abc'
    })
    expect(layoutInvalidations.length).toBeGreaterThan(0)
  })

  it('does NOT invalidate when project_id is missing', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      createElement(QueryClientProvider, { client: qc }, children)

    renderHook(() => useSSE(), { wrapper })
    await waitFor(() => {
      expect(MockEventSource.instances.length).toBeGreaterThan(0)
    })

    act(() => {
      MockEventSource.instances[0].simulate({
        type: 'workbench.layout.updated',
        user_id: 'me',
        // project_id intentionally absent
        data: { client_id: 'tab-other' },
      })
    })

    const layoutInvalidations = invalidateSpy.mock.calls.filter((args) => {
      const opt = args[0] as { queryKey?: unknown[] } | undefined
      const k = opt?.queryKey
      return Array.isArray(k) && k[0] === 'workbench-layout'
    })
    expect(layoutInvalidations.length).toBe(0)
  })
})
