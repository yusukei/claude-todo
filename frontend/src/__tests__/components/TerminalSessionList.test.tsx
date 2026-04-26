/**
 * TerminalSessionList — load / empty / new session / delete.
 */
import { describe, expect, it, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import TerminalSessionList from '../../components/workspace/TerminalSessionList'
import { server } from '../mocks/server'
import { renderWithProviders } from '../utils/renderWithProviders'

const AGENT = 'agent-xyz'

beforeEach(() => {
  // default: empty session list
  server.use(
    http.get(`/api/v1/workspaces/terminal/${AGENT}/sessions`, () =>
      HttpResponse.json({ sessions: [] }),
    ),
  )
})

describe('TerminalSessionList — empty state', () => {
  it('shows nothing-yet copy when there are no sessions', async () => {
    renderWithProviders(<TerminalSessionList agentId={AGENT} />)
    // The component renders some "no sessions" or "new" affordance —
    // assert at least that the New button is present.
    await waitFor(() => {
      const newBtn =
        screen.queryByRole('button', { name: /new|新規|セッション/i }) ??
        screen.queryByText(/no\s*sessions|セッションがありません|アクティブなセッション|new/i)
      expect(newBtn).not.toBeNull()
    })
  })
})

describe('TerminalSessionList — list rendering', () => {
  it('shows a row per session with the cmdline', async () => {
    server.use(
      http.get(`/api/v1/workspaces/terminal/${AGENT}/sessions`, () =>
        HttpResponse.json({
          sessions: [
            {
              session_id: 's-1',
              started_at: 1714003200,
              last_activity: 1714003500,
              cmdline: '/bin/zsh -l',
              alive: true,
            },
          ],
        }),
      ),
    )
    renderWithProviders(<TerminalSessionList agentId={AGENT} />)
    await waitFor(() => {
      expect(screen.queryByText(/\/bin\/zsh/)).not.toBeNull()
    })
  })
})

describe('TerminalSessionList — error state', () => {
  it('renders the failure message when the endpoint 500s', async () => {
    server.use(
      http.get(`/api/v1/workspaces/terminal/${AGENT}/sessions`, () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )
    renderWithProviders(<TerminalSessionList agentId={AGENT} />)
    await waitFor(() => {
      expect(
        screen.queryByText(/Failed to load sessions/i),
      ).not.toBeNull()
    })
  })
})
