/**
 * Phase 1 (Lifecycle & Ownership 仕様書 §3.1, §8 受入基準 #1) 受入テスト。
 *
 * WorkbenchShell が `/projects/:projectId/*` の永続的な親レイアウトとして
 * 機能し、子ルート (settings 等) への遷移で WorkbenchPage が unmount
 * しないことを検証する。
 *
 * Phase 1 の核心:
 *   - 旧設計では `/projects/:projectId` と `/projects/:projectId/settings`
 *     が flat な兄弟ルートだったため、settings に遷移すると WorkbenchPage
 *     element が unmount → 配下の TerminalView も unmount → ws.close()。
 *   - 新設計では settings は WorkbenchShell の子ルートで、WorkbenchShell が
 *     WorkbenchPage を常時 mount し続ける。子ルート要素は overlay として
 *     上に被せるだけ。
 */
import { describe, expect, it, vi } from 'vitest'
import { useEffect } from 'react'
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {
  MemoryRouter,
  Route,
  Routes,
  useNavigate,
} from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import WorkbenchShell from '../../pages/WorkbenchShell'

// WorkbenchPage は重い (useQuery / useWorkbenchStore / panes...) ので、
// 本テストでは mount/unmount 観察に絞った probe で差し替える。
const workbenchMounts = { count: 0 }
const workbenchUnmounts = { count: 0 }

vi.mock('../../pages/WorkbenchPage', () => {
  return {
    default: function ProbeWorkbenchPage() {
      useEffect(() => {
        workbenchMounts.count += 1
        return () => {
          workbenchUnmounts.count += 1
        }
      }, [])
      return <div data-testid="probe-workbench">Workbench</div>
    },
  }
})

function NavBar() {
  const navigate = useNavigate()
  return (
    <div>
      <button
        type="button"
        data-testid="goto-settings"
        onClick={() => navigate('/projects/p-1/settings')}
      >
        settings
      </button>
      <button
        type="button"
        data-testid="goto-workbench"
        onClick={() => navigate('/projects/p-1')}
      >
        workbench
      </button>
    </div>
  )
}

function FakeSettings() {
  return <div data-testid="probe-settings">Settings</div>
}

function renderShell(initialPath: string) {
  workbenchMounts.count = 0
  workbenchUnmounts.count = 0
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <NavBar />
        <Routes>
          <Route path="/projects/:projectId" element={<WorkbenchShell />}>
            <Route path="settings" element={<FakeSettings />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('Phase 1 / WorkbenchShell — 受入基準 #1', () => {
  it('WorkbenchPage is mounted on the index route', () => {
    renderShell('/projects/p-1')
    expect(workbenchMounts.count).toBe(1)
    expect(screen.getByTestId('probe-workbench')).toBeInTheDocument()
  })

  it('navigating to /settings does NOT unmount WorkbenchPage', async () => {
    const user = userEvent.setup()
    renderShell('/projects/p-1')
    expect(workbenchMounts.count).toBe(1)
    await act(async () => {
      await user.click(screen.getByTestId('goto-settings'))
    })
    // Settings overlay is shown
    expect(screen.getByTestId('probe-settings')).toBeInTheDocument()
    // WorkbenchPage probe is still in the DOM (display:none ancestor)
    expect(screen.getByTestId('probe-workbench')).toBeInTheDocument()
    // Critical invariant: never unmounted
    expect(workbenchUnmounts.count).toBe(0)
    // And mount count did not double
    expect(workbenchMounts.count).toBe(1)
  })

  it('settings → workbench round-trip leaves WorkbenchPage mount untouched', async () => {
    const user = userEvent.setup()
    renderShell('/projects/p-1')
    await act(async () => {
      await user.click(screen.getByTestId('goto-settings'))
    })
    await act(async () => {
      await user.click(screen.getByTestId('goto-workbench'))
    })
    expect(workbenchMounts.count).toBe(1)
    expect(workbenchUnmounts.count).toBe(0)
    expect(screen.getByTestId('probe-workbench')).toBeInTheDocument()
    // Settings overlay is gone
    expect(screen.queryByTestId('probe-settings')).toBeNull()
  })

  it('hides WorkbenchPage via display:none while overlay is shown', async () => {
    const user = userEvent.setup()
    renderShell('/projects/p-1')
    const probe = screen.getByTestId('probe-workbench')
    // Pre-overlay: visible (no hidden ancestor)
    expect(isHiddenByDisplayNone(probe)).toBe(false)
    await act(async () => {
      await user.click(screen.getByTestId('goto-settings'))
    })
    // Post-overlay: hidden via display:none on an ancestor
    expect(isHiddenByDisplayNone(probe)).toBe(true)
  })
})

function isHiddenByDisplayNone(el: HTMLElement | null): boolean {
  let cursor: HTMLElement | null = el
  while (cursor) {
    if (cursor.style.display === 'none') return true
    cursor = cursor.parentElement
  }
  return false
}
