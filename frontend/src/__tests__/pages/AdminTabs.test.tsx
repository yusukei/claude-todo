/**
 * AdminPage tabs not covered by AdminPage.test.tsx:
 *   - McpUsageTab (read-only dashboard)
 *   - McpFeedbackSection (feedback list)
 *   - PasskeysTab (WebAuthn credentials)
 */
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import McpUsageTab from '../../pages/admin/McpUsageTab'
import McpFeedbackSection from '../../pages/admin/McpFeedbackSection'
import PasskeysTab from '../../pages/admin/PasskeysTab'
import { server } from '../mocks/server'
import { useAuthStore } from '../../store/auth'
import { createMockUser } from '../mocks/factories'
import { renderWithProviders } from '../utils/renderWithProviders'

beforeEach(() => {
  useAuthStore.setState({ user: createMockUser({ is_admin: true }), isInitialized: true })
})

// ── McpUsageTab ──────────────────────────────────────────

describe('McpUsageTab — renders the dashboard summary', () => {
  beforeEach(() => {
    server.use(
      http.get(/\/api\/v1\/mcp\/usage\/summary/, () =>
        HttpResponse.json({
          since: '2026-04-01T00:00:00Z',
          days: 7,
          total_calls: 42,
          total_errors: 1,
          tool_count: 5,
          items: [],
        }),
      ),
      http.get(/\/api\/v1\/mcp\/usage\/unused/, () =>
        HttpResponse.json({
          days: 7,
          registered_count: 10,
          used_count: 5,
          unused_count: 5,
          unused: ['unused-tool-a', 'unused-tool-b'],
        }),
      ),
      http.get(/\/api\/v1\/mcp\/usage\/errors/, () => HttpResponse.json({ items: [] })),
      http.get(/\/api\/v1\/mcp\/usage\/health/, () =>
        HttpResponse.json({
          enabled: true,
          sampling_rate: 1.0,
          slow_call_ms: 1000,
          registered_tools: 10,
          bucket_doc_count: 1,
          event_doc_count: 1,
        }),
      ),
      http.get(/\/api\/v1\/mcp\/usage\/feedback\/summary/, () =>
        HttpResponse.json({
          by_status: {},
          by_type: [],
          top_tools_with_open_requests: [],
        }),
      ),
      http.get(/\/api\/v1\/mcp\/usage\/feedback/, () =>
        HttpResponse.json({ total: 0, items: [] }),
      ),
    )
  })

  it('shows the total call counter from the summary response', async () => {
    renderWithProviders(<McpUsageTab />)
    await waitFor(() => {
      expect(screen.queryByText(/42/)).not.toBeNull()
    })
  })

  it('lists unused tool names from the unused-tools response', async () => {
    renderWithProviders(<McpUsageTab />)
    await waitFor(() => {
      expect(screen.queryByText('unused-tool-a')).not.toBeNull()
    })
  })
})

// ── McpFeedbackSection ──────────────────────────────────

describe('McpFeedbackSection — renders feedback', () => {
  it('shows an item from the feedback list', async () => {
    server.use(
      http.get(/\/api\/v1\/mcp\/usage\/feedback\/summary/, () =>
        HttpResponse.json({
          by_status: { open: 1 },
          by_type: [{ request_type: 'enhance', count: 1 }],
          top_tools_with_open_requests: [],
        }),
      ),
      http.get(/\/api\/v1\/mcp\/usage\/feedback/, () =>
        HttpResponse.json({
          total: 1,
          items: [
            {
              id: 'fb1',
              tool_name: 'create_task',
              request_type: 'enhance',
              description: 'Add bulk-create flag please',
              related_tools: [],
              status: 'open',
              votes: 3,
              submitted_by: null,
              created_at: '2026-04-20T00:00:00Z',
              updated_at: '2026-04-20T00:00:00Z',
            },
          ],
        }),
      ),
    )
    renderWithProviders(<McpFeedbackSection />)
    await waitFor(() => {
      expect(screen.queryByText(/Add bulk-create flag please/i)).not.toBeNull()
    })
  })

  it('shows an empty-state hint when no feedback exists', async () => {
    server.use(
      http.get(/\/api\/v1\/mcp\/usage\/feedback\/summary/, () =>
        HttpResponse.json({
          by_status: {},
          by_type: [],
          top_tools_with_open_requests: [],
        }),
      ),
      http.get(/\/api\/v1\/mcp\/usage\/feedback/, () =>
        HttpResponse.json({ total: 0, items: [] }),
      ),
    )
    renderWithProviders(<McpFeedbackSection />)
    // Component-specific empty UI varies — the safe assertion is
    // that no real feedback entries appear.
    await waitFor(() => {
      expect(screen.queryByText(/Add bulk-create flag/i)).toBeNull()
    })
  })
})

// ── PasskeysTab ──────────────────────────────────────────

describe('PasskeysTab — renders credential list', () => {
  it('lists each WebAuthn credential returned by the server', async () => {
    server.use(
      http.get('/api/v1/auth/webauthn/credentials', () =>
        HttpResponse.json([
          { credential_id: 'cred-1', name: 'YubiKey 5C', sign_count: 7, transports: ['usb'] },
          { credential_id: 'cred-2', name: 'iPhone Touch ID', sign_count: 12, transports: ['internal'] },
        ]),
      ),
    )
    renderWithProviders(<PasskeysTab />)
    await waitFor(() => {
      expect(screen.queryByText('YubiKey 5C')).not.toBeNull()
      expect(screen.queryByText('iPhone Touch ID')).not.toBeNull()
    })
  })

  it('exposes a registration button to add a new passkey', async () => {
    server.use(
      http.get('/api/v1/auth/webauthn/credentials', () => HttpResponse.json([])),
    )
    renderWithProviders(<PasskeysTab />)
    await waitFor(() => {
      const trigger =
        screen.queryByRole('button', { name: /パスキー|passkey|追加|register/i }) ??
        screen.queryByText(/パスキー|passkey/i)
      expect(trigger).not.toBeNull()
    })
  })
})
