/**
 * TerminalPane "no agent bound" CTA (TM1).
 *
 * When the project has no remote agent, the pane must NOT silently
 * blank out — it must show a CTA pointing the user to the project
 * settings page so they can bind an agent.
 */
import { describe, expect, it, vi, beforeAll } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import TerminalPane from '../../workbench/panes/TerminalPane'
import { WorkbenchEventProvider } from '../../workbench/eventBus'
import { server } from '../mocks/server'
import type { TabsNode } from '../../workbench/types'

const PROJECT_ID = '69bfffad73ed736a9d13fd0f'

const TREE: TabsNode = {
  kind: 'tabs',
  id: 'g1',
  activeTabId: 'p1',
  tabs: [{ id: 'p1', paneType: 'terminal', paneConfig: {} }],
}

beforeAll(() => {
  if (!('ResizeObserver' in globalThis)) {
    ;(globalThis as { ResizeObserver?: unknown }).ResizeObserver = vi
      .fn()
      .mockImplementation(() => ({
        observe: vi.fn(),
        disconnect: vi.fn(),
      }))
  }
})

function renderPane(opts: { remote: { agent_id: string } | null }) {
  server.use(
    http.get(`/api/v1/projects/${PROJECT_ID}`, () =>
      HttpResponse.json({
        id: PROJECT_ID,
        name: 'P',
        members: [],
        remote: opts.remote,
        status: 'active',
        is_locked: false,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }),
    ),
  )
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <WorkbenchEventProvider tree={TREE}>
          <TerminalPane
            paneId="p1"
            projectId={PROJECT_ID}
            paneConfig={{}}
            onConfigChange={vi.fn()}
          />
        </WorkbenchEventProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Workbench / TerminalPane — TM1: no-agent CTA', () => {
  it('shows a settings link when project.remote is null', async () => {
    renderPane({ remote: null })
    await waitFor(() => {
      // "Open project settings" / "プロジェクト設定" CTA — accept either
      // text label or a link to the settings route.
      const settingsLink = screen.queryByRole('link', {
        name: /プロジェクト設定|project settings|settings/i,
      })
      expect(settingsLink).not.toBeNull()
      expect(settingsLink?.getAttribute('href')).toContain(`/projects/${PROJECT_ID}/settings`)
    })
  })

  it('mentions the missing agent in the empty state copy', async () => {
    renderPane({ remote: null })
    await waitFor(() => {
      const text = document.body.textContent ?? ''
      expect(text).toMatch(/agent/i)
    })
  })
})
