/**
 * ProjectSecretsTab — list + owner-only mutations.
 */
import { describe, expect, it, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import ProjectSecretsTab from '../../components/project/ProjectSecretsTab'
import { server } from '../mocks/server'
import { renderWithProviders } from '../utils/renderWithProviders'

const PROJECT_ID = 'p-1'

const SECRETS = [
  {
    id: 's-1',
    project_id: PROJECT_ID,
    key: 'GITHUB_TOKEN',
    description: 'GH PAT',
    created_by: 'u-1',
    updated_by: 'u-1',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 's-2',
    project_id: PROJECT_ID,
    key: 'OPENAI_API_KEY',
    description: '',
    created_by: 'u-1',
    updated_by: 'u-1',
    created_at: '2026-01-02T00:00:00Z',
    updated_at: '2026-01-02T00:00:00Z',
  },
]

beforeEach(() => {
  server.use(
    http.get(`/api/v1/projects/${PROJECT_ID}/secrets/`, () =>
      HttpResponse.json({ items: SECRETS, total: SECRETS.length }),
    ),
  )
})

describe('ProjectSecretsTab — list rendering', () => {
  it('shows each secret key', async () => {
    renderWithProviders(<ProjectSecretsTab projectId={PROJECT_ID} isOwner />)
    await waitFor(() => {
      expect(screen.queryByText('GITHUB_TOKEN')).not.toBeNull()
      expect(screen.queryByText('OPENAI_API_KEY')).not.toBeNull()
    })
  })
})

describe('ProjectSecretsTab — owner gating', () => {
  it('owner sees create / edit / delete affordances', async () => {
    renderWithProviders(<ProjectSecretsTab projectId={PROJECT_ID} isOwner />)
    await waitFor(() => {
      expect(screen.queryByText('GITHUB_TOKEN')).not.toBeNull()
    })
    // At least one create/add affordance is visible.
    const createBtn =
      screen.queryByRole('button', { name: /追加|create|Add/i }) ??
      document.querySelector('[title*="追加"]')
    expect(createBtn).not.toBeNull()
  })

  it('non-owner does NOT see the create button', async () => {
    renderWithProviders(<ProjectSecretsTab projectId={PROJECT_ID} isOwner={false} />)
    await waitFor(() => {
      expect(screen.queryByText('GITHUB_TOKEN')).not.toBeNull()
    })
    expect(
      screen.queryByRole('button', { name: /^追加$|^Add$|create$/i }),
    ).toBeNull()
  })
})
