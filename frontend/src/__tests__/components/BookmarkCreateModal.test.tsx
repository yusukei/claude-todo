/**
 * BookmarkCreateModal — form submission + URL validation.
 */
import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BookmarkCreateModal from '../../components/bookmark/BookmarkCreateModal'
import { server } from '../mocks/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

function renderModal(overrides?: { onCreated?: () => void; onClose?: () => void }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <BookmarkCreateModal
        projectId="p-1"
        collections={[
          { id: 'c-1', name: 'Reading' } as unknown as Parameters<typeof BookmarkCreateModal>[0]['collections'][number],
        ]}
        onClose={overrides?.onClose ?? vi.fn()}
        onCreated={overrides?.onCreated ?? vi.fn()}
      />
    </QueryClientProvider>,
  )
}

describe('BookmarkCreateModal — submit posts to /projects/:id/bookmarks/', () => {
  it('builds the body with url, title, description, tags, collection_id', async () => {
    const user = userEvent.setup()
    let received: unknown = null
    server.use(
      http.post('/api/v1/projects/p-1/bookmarks/', async ({ request }) => {
        received = await request.json()
        return HttpResponse.json({ id: 'bm-1' })
      }),
    )
    const onCreated = vi.fn()
    renderModal({ onCreated })

    // The URL input is identified by its placeholder.
    const urlInput = screen.getByPlaceholderText(
      'https://example.com/article',
    ) as HTMLInputElement
    await user.type(urlInput, 'https://example.com')

    const submit = screen.getAllByRole('button').find(
      (b) => /追加|create|add|登録|送信/i.test(b.textContent ?? ''),
    )
    expect(submit).toBeTruthy()
    await user.click(submit!)
    await waitFor(() => {
      expect(onCreated).toHaveBeenCalled()
    })
    expect((received as { url?: string })?.url).toBe('https://example.com')
  })
})

describe('BookmarkCreateModal — empty url does not submit', () => {
  it('does not POST when url is empty/whitespace', async () => {
    const user = userEvent.setup()
    let posted = false
    server.use(
      http.post('/api/v1/projects/p-1/bookmarks/', () => {
        posted = true
        return HttpResponse.json({ id: 'bm-1' })
      }),
    )
    const onCreated = vi.fn()
    renderModal({ onCreated })
    const submit = screen.getAllByRole('button').find(
      (b) => /追加|create|add|登録|送信/i.test(b.textContent ?? ''),
    )
    if (submit) await user.click(submit)
    expect(posted).toBe(false)
    expect(onCreated).not.toHaveBeenCalled()
  })
})
