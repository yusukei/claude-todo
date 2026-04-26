/**
 * DocPane invariants (D1, D2).
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import DocPane from '../../workbench/panes/DocPane'
import { WorkbenchEventProvider } from '../../workbench/eventBus'
import { server } from '../mocks/server'
import type { TabsNode } from '../../workbench/types'

const PROJECT_ID = '69bfffad73ed736a9d13fd0f'
const TREE: TabsNode = {
  kind: 'tabs',
  id: 'g1',
  activeTabId: 'p1',
  tabs: [{ id: 'p1', paneType: 'doc', paneConfig: {} }],
}

beforeEach(() => {
  server.use(
    http.get(`/api/v1/projects/${PROJECT_ID}/documents/`, () =>
      HttpResponse.json({ items: [{ id: 'doc-1', title: 'Spec', category: 'spec', updated_at: '2026-01-01T00:00:00Z' }], total: 1 }),
    ),
    http.get(`/api/v1/projects/${PROJECT_ID}/documents/:docId`, ({ params }) =>
      HttpResponse.json({
        id: params.docId as string,
        title: 'Doc Title',
        category: 'spec',
        content: '# hello',
        tags: [],
        updated_at: '2026-01-01T00:00:00Z',
      }),
    ),
  )
})

function renderPane(opts: { docId?: string }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <WorkbenchEventProvider tree={TREE}>
          <DocPane
            paneId="p1"
            projectId={PROJECT_ID}
            paneConfig={opts.docId ? { docId: opts.docId } : {}}
            onConfigChange={vi.fn()}
          />
        </WorkbenchEventProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Workbench / DocPane — D1: empty state with picker when no docId', () => {
  it('renders a picker affordance when paneConfig.docId is absent', async () => {
    renderPane({})
    await waitFor(() => {
      // Picker shows the doc list — at least our seeded "Spec" entry.
      expect(screen.queryByText('Spec')).not.toBeNull()
    })
  })
})

describe('Workbench / DocPane — D2: Open in editor link present when doc loaded', () => {
  it('renders a link to /projects/:id/documents/:did when a doc is selected', async () => {
    renderPane({ docId: 'doc-1' })
    await waitFor(() => {
      const links = Array.from(document.querySelectorAll('a'))
      const open = links.find(
        (a) => a.getAttribute('href') === `/projects/${PROJECT_ID}/documents/doc-1`,
      )
      expect(open, 'expected an "Open" link to the full document page').toBeTruthy()
    })
  })
})
