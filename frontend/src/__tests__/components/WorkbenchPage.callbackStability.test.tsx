/**
 * WorkbenchPage callback identity stability (C1).
 *
 * The callbacks passed from WorkbenchPage to its children
 * (`onConfigChange`, `onActivateTab`, `onCloseTab`, `onAddTab`,
 * `onSplit`, `onCloseGroup`, `onSplitSizes`,
 * `onMoveTab`) MUST retain their identity across `state.tree`
 * changes. Otherwise downstream components — most importantly
 * `TerminalView`, whose useEffect deps include the callback — tear
 * down and recreate their WebSockets on every layout change,
 * producing the visible "reconnect cascade" the user reported.
 *
 * The test mounts a probe in place of the layout subtree; the probe
 * captures every callback prop on every render. We then trigger a
 * `state.tree` change by invoking the captured `onConfigChange` and
 * assert that the next render delivers the SAME function references.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { useEffect, useRef } from 'react'
import { act, render, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import WorkbenchPage from '../../pages/WorkbenchPage'
import { server } from '../mocks/server'

const PROJECT_A = '69bfffad73ed736a9d13fd0f'

interface CapturedCallbacks {
  onConfigChange?: (paneId: string, patch: Record<string, unknown>) => void
  onActivateTab?: (groupId: string, tabId: string) => void
  onCloseTab?: (groupId: string, tabId: string) => void
  onAddTab?: (groupId: string, paneType: string) => void
  onSplit?: (groupId: string, orientation: string) => void
  onCloseGroup?: (groupId: string) => void
  onSplitSizes?: (splitId: string, sizes: number[]) => void
  onMoveTab?: (paneId: string, targetGroupId: string, drop: unknown) => void
}

// Each render's snapshot of the callback identities.
const renderHistory: CapturedCallbacks[] = []

// Mock WorkbenchLayout (the component that fans the callbacks down).
vi.mock('../../workbench/WorkbenchLayout', () => {
  function ProbeLayout(props: CapturedCallbacks & { tree: unknown; projectId: string }) {
    const ref = useRef(0)
    useEffect(() => {
      ref.current += 1
    })
    renderHistory.push({
      onConfigChange: props.onConfigChange,
      onActivateTab: props.onActivateTab,
      onCloseTab: props.onCloseTab,
      onAddTab: props.onAddTab,
      onSplit: props.onSplit,
      onCloseGroup: props.onCloseGroup,
      onSplitSizes: props.onSplitSizes,
      onMoveTab: props.onMoveTab,
      // Capture the tree too so the test can pick a real groupId.
      ...({ tree: props.tree } as unknown as CapturedCallbacks),
    })
    return <div data-testid="probe-layout" />
  }
  return { default: ProbeLayout, useRegisterTabStripFn: () => () => () => {} }
})

beforeEach(() => {
  renderHistory.length = 0
  window.sessionStorage.setItem('workbench:clientId', 'this-tab')
  server.use(
    http.get('/api/v1/projects/:projectId', () =>
      HttpResponse.json({
        id: 'pid',
        name: 'project',
        members: [],
        remote: null,
        status: 'active',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }),
    ),
    http.get('/api/v1/workbench/layouts/:projectId', () =>
      HttpResponse.json({ detail: 'not found' }, { status: 404 }),
    ),
    http.put('/api/v1/workbench/layouts/:projectId', () =>
      HttpResponse.json({ updated_at: 'ts' }),
    ),
  )
})

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/projects/${PROJECT_A}`]}>
        <Routes>
          <Route path="/projects/:projectId" element={<WorkbenchPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Workbench / Callbacks — C1: callback ref stability across state.tree changes', () => {
  it('all layout-mutating callbacks retain identity after a real layout mutation', async () => {
    renderPage()
    await waitFor(() => {
      expect(renderHistory.length).toBeGreaterThan(0)
    })
    const initial = renderHistory[renderHistory.length - 1]
    expect(initial.onAddTab).toBeTypeOf('function')

    // Trigger a state.tree mutation that ACTUALLY changes the tree.
    // The probe wrapper above stores the tree as `unknown`; reach into
    // it just enough to find a tab group id so onAddTab succeeds.
    // We rely on the default layout being a single tabs group.
    await act(async () => {
      // Find the active group id from the captured tree on the probe.
      // We bound the fetched onConfigChange shape minimally for the
      // assertion — to find a real groupId we rerun the layout via
      // onSplit which always produces a structural change.
      // A horizontal split on the root group is a no-op when the tree
      // is already at the cap — but the default layout has 1 group, so
      // splitting works. Pass a definitely-existing group id:
      // the default layout's root id can be found via the initial tree
      // captured above.
      // Simpler approach: emit a configChange with a paneId that may or
      // may not match — but a bigger mutation via onSplit reliably
      // changes the tree structure.
      // Use the captured tree's first group id.
      const tree = (renderHistory[renderHistory.length - 1] as unknown as {
        tree?: { id: string; kind: string }
      }).tree
      // Fall back: just call onSplit on a guessed id; if it's wrong,
      // updateTree's validator rejects and the test fails loudly.
      const groupId = tree?.id ?? ''
      initial.onSplit!(groupId, 'horizontal')
    })

    const latest = renderHistory[renderHistory.length - 1]
    // Sanity: the tree DID change (otherwise this test would pass
    // vacuously like the previous version did).
    const initialTree = (initial as unknown as { tree?: unknown }).tree
    const latestTree = (latest as unknown as { tree?: unknown }).tree
    expect(latestTree).not.toBe(initialTree)

    const keys: Array<keyof CapturedCallbacks> = [
      'onConfigChange',
      'onActivateTab',
      'onCloseTab',
      'onAddTab',
      'onSplit',
      'onCloseGroup',
      'onSplitSizes',
      'onMoveTab',
    ]
    for (const k of keys) {
      expect(latest[k], `${k} should retain identity`).toBe(initial[k])
    }
  })
})
