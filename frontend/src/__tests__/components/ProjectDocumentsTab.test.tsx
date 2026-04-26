/**
 * ProjectDocumentsTab — high-value affordances.
 *
 * Invariants (PD-prefix):
 *   PD1 The document list renders one entry per server-returned doc.
 *   PD2 The "+ 追加" button starts the create flow.
 *   PD3 Clicking a list entry calls ``onSelectId`` with that id.
 *   PD4 The search input filters the visible list (case-insensitive).
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ProjectDocumentsTab from '../../components/project/ProjectDocumentsTab'
import { server } from '../mocks/server'

// jsdom + MarkdownRenderer's remark plugins crash on a few edges
// unrelated to the affordances we're testing here. Stub it.
vi.mock('../../components/common/MarkdownRenderer', () => ({
  default: function MockMd({ children }: { children?: string }) {
    return <div data-testid="md">{String(children ?? '')}</div>
  },
}))

const PROJECT_ID = 'proj-x'

const docs = [
  {
    id: 'd-spec',
    title: 'Spec Document',
    category: 'spec',
    tags: ['design'],
    updated_at: '2026-04-01T00:00:00Z',
  },
  {
    id: 'd-notes',
    title: 'Meeting Notes',
    category: 'notes',
    tags: [],
    updated_at: '2026-04-02T00:00:00Z',
  },
]

beforeEach(() => {
  server.use(
    http.get(`/api/v1/projects/${PROJECT_ID}/documents/`, ({ request }) => {
      const url = new URL(request.url)
      const search = url.searchParams.get('search')?.toLowerCase() ?? ''
      const filtered = search
        ? docs.filter((d) => d.title.toLowerCase().includes(search))
        : docs
      return HttpResponse.json({ items: filtered, total: filtered.length })
    }),
    http.get(`/api/v1/projects/${PROJECT_ID}/documents/:docId`, ({ params }) =>
      HttpResponse.json({
        id: params.docId as string,
        title: 'Loaded',
        category: 'spec',
        tags: [],
        content: '# Hello',
        updated_at: '2026-04-01T00:00:00Z',
      }),
    ),
  )
})

function renderTab(opts?: { onSelectId?: (id: string | null) => void }) {
  const onSelectId = opts?.onSelectId ?? vi.fn()
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  })
  return {
    onSelectId,
    ...render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <ProjectDocumentsTab projectId={PROJECT_ID} onSelectId={onSelectId} />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  }
}

describe('ProjectDocumentsTab — PD1: renders one entry per document', () => {
  it('shows both seeded documents', async () => {
    renderTab()
    await waitFor(() => {
      expect(screen.queryByText('Spec Document')).not.toBeNull()
      expect(screen.queryByText('Meeting Notes')).not.toBeNull()
    })
  })
})

describe('ProjectDocumentsTab — PD2: "+ 追加" starts the create flow', () => {
  it('opens an editor / form (not a no-op) when the add button is clicked', async () => {
    const user = userEvent.setup()
    renderTab()
    await waitFor(() => {
      expect(screen.queryByText('Spec Document')).not.toBeNull()
    })
    const addBtn = screen.getByRole('button', { name: /追加/i })
    await user.click(addBtn)
    // Some "create" affordance becomes visible. Accept either an
    // input-titled "タイトル" or a "保存" / "Save" CTA in the form.
    await waitFor(() => {
      const matched =
        screen.queryByPlaceholderText(/タイトル|title/i) ??
        screen.queryByLabelText(/タイトル|title/i) ??
        screen.queryByRole('button', { name: /保存|Save|作成|Create/i })
      expect(matched).not.toBeNull()
    })
  })
})

describe('ProjectDocumentsTab — PD3: clicking a list entry calls onSelectId', () => {
  it('invokes onSelectId with the clicked document id', async () => {
    const user = userEvent.setup()
    const { onSelectId } = renderTab()
    await waitFor(() => {
      expect(screen.queryByText('Spec Document')).not.toBeNull()
    })
    await user.click(screen.getByText('Spec Document'))
    await waitFor(() => {
      expect(onSelectId).toHaveBeenCalledWith('d-spec')
    })
  })
})

describe('ProjectDocumentsTab — PD4: search filters the visible list', () => {
  it('typing in the search box hides non-matching entries', async () => {
    const user = userEvent.setup()
    renderTab()
    await waitFor(() => {
      expect(screen.queryByText('Spec Document')).not.toBeNull()
      expect(screen.queryByText('Meeting Notes')).not.toBeNull()
    })
    const search = screen.getByPlaceholderText(/検索/)
    await user.type(search, 'meeting')
    await waitFor(() => {
      expect(screen.queryByText('Meeting Notes')).not.toBeNull()
      expect(screen.queryByText('Spec Document')).toBeNull()
    })
  })
})
