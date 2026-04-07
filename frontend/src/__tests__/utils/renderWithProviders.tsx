import React from 'react'
import { render, type RenderOptions, type RenderResult } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

/**
 * Shared test render helper.
 *
 * Wraps the UI in a QueryClientProvider (with retries disabled so failing
 * mocks don't slow tests down) and a MemoryRouter. Optional `route` and
 * `path` parameters let consumers exercise URL-aware components without
 * having to set up the router boilerplate themselves.
 *
 *     renderWithProviders(<ProjectsPage />)
 *     renderWithProviders(<ProjectPage />, {
 *       route: '/projects/abc123',
 *       path: '/projects/:projectId',
 *     })
 *
 * The QueryClient instance is fresh on every call so tests don't share
 * cached query results — pass `queryClient` to override when you need
 * to seed cache state.
 */
export interface RenderWithProvidersOptions extends Omit<RenderOptions, 'wrapper'> {
  /** Initial URL for the MemoryRouter (default `/`). */
  route?: string
  /** Optional Route path pattern. When set, the UI is rendered through a Routes/Route pair. */
  path?: string
  /** Override the QueryClient (useful for seeding cache state). */
  queryClient?: QueryClient
}

export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  })
}

export function renderWithProviders(
  ui: React.ReactElement,
  options: RenderWithProvidersOptions = {},
): RenderResult & { queryClient: QueryClient } {
  const { route = '/', path, queryClient = createTestQueryClient(), ...rest } = options

  const wrapped = path ? (
    <Routes>
      <Route path={path} element={ui} />
    </Routes>
  ) : (
    ui
  )

  const result = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{wrapped}</MemoryRouter>
    </QueryClientProvider>,
    rest,
  )

  return { ...result, queryClient }
}
