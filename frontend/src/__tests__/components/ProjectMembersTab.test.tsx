/**
 * ProjectMembersTab — list members + owner-only affordances.
 */
import { describe, expect, it, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import ProjectMembersTab from '../../components/project/ProjectMembersTab'
import { server } from '../mocks/server'
import { useAuthStore } from '../../store/auth'
import { createMockUser } from '../mocks/factories'
import { renderWithProviders } from '../utils/renderWithProviders'
import type { Project } from '../../types'

const owner = createMockUser({ id: 'u-owner', name: 'Owner', email: 'o@x' })
const member = createMockUser({ id: 'u-member', name: 'Member', email: 'm@x' })

const project: Project = {
  id: 'p-1',
  name: 'P',
  color: '#ccc',
  status: 'active',
  is_locked: false,
  members: [
    { user_id: 'u-owner', role: 'owner', joined_at: '2026-01-01T00:00:00Z' },
    { user_id: 'u-member', role: 'member', joined_at: '2026-01-02T00:00:00Z' },
  ],
  created_by: 'u-owner',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
} as unknown as Project

beforeEach(() => {
  // The component fetches member info through /users/search/active —
  // both for the new-member typeahead (q=...) and for the bulk
  // resolver (limit=50, no q). Return the seeded user list either way.
  server.use(
    http.get(/\/api\/v1\/users\/search\/active/, () =>
      HttpResponse.json([owner, member]),
    ),
  )
})

describe('ProjectMembersTab — render', () => {
  it('lists each member with name + role', async () => {
    useAuthStore.setState({ user: owner, isInitialized: true })
    renderWithProviders(<ProjectMembersTab project={project} />)
    await waitFor(() => {
      expect(screen.queryByText('Owner')).not.toBeNull()
      expect(screen.queryByText('Member')).not.toBeNull()
    })
  })
})

describe('ProjectMembersTab — owner-only affordances', () => {
  it('shows the add-member affordance when current user is owner', async () => {
    useAuthStore.setState({ user: owner, isInitialized: true })
    renderWithProviders(<ProjectMembersTab project={project} />)
    await waitFor(() => {
      // accept either "メンバー追加" / "ユーザー" / "Add" button
      const matched =
        screen.queryByRole('button', { name: /追加|Add|招待|招待する/i }) ??
        screen.queryByLabelText(/追加|add/i)
      expect(matched).not.toBeNull()
    })
  })

  it('hides add-member affordance for non-owner non-admin', async () => {
    useAuthStore.setState({
      user: { ...member, is_admin: false } as ReturnType<typeof createMockUser>,
      isInitialized: true,
    })
    renderWithProviders(<ProjectMembersTab project={project} />)
    // Wait for member list to render so we know component mounted.
    await waitFor(() => {
      expect(screen.queryByText('Member')).not.toBeNull()
    })
    expect(
      screen.queryByRole('button', { name: /追加|Add|招待/i }),
    ).toBeNull()
  })
})
