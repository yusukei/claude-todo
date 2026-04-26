/**
 * BookmarkCollectionSidebar — list collections + select + add.
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BookmarkCollectionSidebar from '../../components/bookmark/BookmarkCollectionSidebar'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { BookmarkCollection } from '../../types'

function renderSidebar(
  overrides: Partial<Parameters<typeof BookmarkCollectionSidebar>[0]> = {},
) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onSelectCollection = overrides.onSelectCollection ?? vi.fn()
  const onToggleStarred = overrides.onToggleStarred ?? vi.fn()
  return {
    onSelectCollection,
    onToggleStarred,
    ...render(
      <QueryClientProvider client={qc}>
        <BookmarkCollectionSidebar
          projectId="p-1"
          collections={[
            { id: 'c-A', name: 'Reading' } as unknown as BookmarkCollection,
            { id: 'c-B', name: 'Watch later' } as unknown as BookmarkCollection,
          ]}
          selectedCollection={null}
          onSelectCollection={onSelectCollection}
          starred={false}
          onToggleStarred={onToggleStarred}
          {...overrides}
        />
      </QueryClientProvider>,
    ),
  }
}

describe('BookmarkCollectionSidebar — list', () => {
  it('lists each collection name', () => {
    renderSidebar()
    expect(screen.getByText('Reading')).toBeInTheDocument()
    expect(screen.getByText('Watch later')).toBeInTheDocument()
  })
})

describe('BookmarkCollectionSidebar — selection', () => {
  it('clicking a collection calls onSelectCollection with its id', async () => {
    const user = userEvent.setup()
    const { onSelectCollection } = renderSidebar()
    await user.click(screen.getByText('Reading'))
    expect(onSelectCollection).toHaveBeenCalledWith('c-A')
  })
})

describe('BookmarkCollectionSidebar — starred toggle', () => {
  it('clicking the starred filter calls onToggleStarred', async () => {
    const user = userEvent.setup()
    const { onToggleStarred } = renderSidebar()
    // Some "Starred" / "スター" affordance exists.
    const starred =
      screen.queryByText(/スター|starred|★/i) ??
      screen.queryByLabelText(/star/i)
    expect(starred).not.toBeNull()
    if (starred) await user.click(starred)
    expect(onToggleStarred).toHaveBeenCalled()
  })
})
