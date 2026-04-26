/**
 * FileBrowserPane invariants (FB1).
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import FileBrowserPane from '../../workbench/panes/FileBrowserPane'
import { WorkbenchEventProvider, useWorkbenchEvent } from '../../workbench/eventBus'
import { server } from '../mocks/server'
import type { TabsNode } from '../../workbench/types'

const PROJECT_ID = '69bfffad73ed736a9d13fd0f'
const TREE: TabsNode = {
  kind: 'tabs',
  id: 'g1',
  activeTabId: 'p-fb',
  // Include a terminal pane in the tree so the bus has a valid
  // ``open-terminal-cwd`` target type. The probe below subscribes
  // directly to capture the emitted payload.
  tabs: [
    { id: 'p-fb', paneType: 'file-browser', paneConfig: {} },
    { id: 'p-term', paneType: 'terminal', paneConfig: {} },
  ],
}

beforeEach(() => {
  server.use(
    http.get(/\/api\/v1\/workspaces\/projects\/.*\/files/, () =>
      HttpResponse.json({
        entries: [
          { name: 'src', type: 'directory', size: null, mtime: 0 },
          { name: 'README.md', type: 'file', size: 100, mtime: 0 },
        ],
        count: 2,
        path: '.',
      }),
    ),
  )
})

function renderPane(captured: { events: Array<{ topic: string; payload: unknown }> }) {
  function Probe() {
    useWorkbenchEvent('p-term', 'open-terminal-cwd', (payload) => {
      captured.events.push({ topic: 'open-terminal-cwd', payload })
    })
    return null
  }
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <WorkbenchEventProvider tree={TREE}>
          <FileBrowserPane
            paneId="p-fb"
            projectId={PROJECT_ID}
            paneConfig={{}}
            onConfigChange={vi.fn()}
          />
          <Probe />
        </WorkbenchEventProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Workbench / FileBrowserPane — FB1: directory Cmd/Ctrl+click emits open-terminal-cwd', () => {
  it('fires the event with the directory path when a directory is meta-clicked', async () => {
    const captured = { events: [] as Array<{ topic: string; payload: unknown }> }
    renderPane(captured)
    // Wait for the file list to render the seeded "src" directory.
    await waitFor(() => {
      expect(screen.queryByText('src')).not.toBeNull()
    })
    const dirRow = screen.getByText('src').closest('button') ?? screen.getByText('src')
    fireEvent.click(dirRow, { metaKey: true })
    expect(captured.events).toHaveLength(1)
    expect(captured.events[0].topic).toBe('open-terminal-cwd')
    expect(captured.events[0].payload).toEqual(expect.objectContaining({ cwd: 'src' }))
  })

  it('a plain click navigates the pane (does NOT emit open-terminal-cwd)', async () => {
    const captured = { events: [] as Array<{ topic: string; payload: unknown }> }
    renderPane(captured)
    await waitFor(() => {
      expect(screen.queryByText('src')).not.toBeNull()
    })
    const dirRow = screen.getByText('src').closest('button') ?? screen.getByText('src')
    fireEvent.click(dirRow)
    expect(captured.events).toHaveLength(0)
  })
})
