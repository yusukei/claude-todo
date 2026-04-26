import { act, render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useEffect } from 'react'
import {
  WorkbenchEventProvider,
  useWorkbenchEvent,
  useWorkbenchEventBus,
} from '../../workbench/eventBus'
import type { LayoutTree } from '../../workbench/types'

// ── Toast spy ────────────────────────────────────────────────
//
// The bus calls ``showInfoToast`` on routing failure. We swap the
// module export so we can assert on the message without needing the
// real DOM toast container.
const toastSpy = vi.fn()
vi.mock('../../components/common/Toast', () => ({
  showInfoToast: (m: string) => toastSpy(m),
}))

// ── Layout fixtures ──────────────────────────────────────────

const tabs = (id: string, panes: { id: string; type: string }[]): LayoutTree =>
  ({
    id,
    kind: 'tabs',
    tabs: panes.map((p) => ({
      id: p.id,
      paneType: p.type as never,
      paneConfig: {},
    })),
    activeTabId: panes[0].id,
  } as unknown as LayoutTree)

// ── Test harness ─────────────────────────────────────────────
//
// Mounts a tree and exposes the bus + a programmatic subscribe hook
// so each test can assert against received payloads without setting
// up a full pane component.

interface Captured {
  bus: ReturnType<typeof useWorkbenchEventBus>
  received: Map<string, unknown[]>
}

function HarnessChild({
  paneIds,
  capture,
}: {
  paneIds: { id: string; event: 'open-doc' | 'open-terminal-cwd' | 'open-task' }[]
  capture: Captured
}) {
  const bus = useWorkbenchEventBus()
  useEffect(() => {
    capture.bus = bus
  }, [bus, capture])
  // One useWorkbenchEvent call per test pane.
  paneIds.forEach((p) =>
    // eslint-disable-next-line react-hooks/rules-of-hooks
    useWorkbenchEvent(p.id, p.event, (payload) => {
      const list = capture.received.get(p.id) ?? []
      list.push(payload)
      capture.received.set(p.id, list)
    }),
  )
  return null
}

function renderHarness(
  tree: LayoutTree,
  subscriptions: { id: string; event: 'open-doc' | 'open-terminal-cwd' | 'open-task' }[],
) {
  const capture: Captured = {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    bus: undefined as any,
    received: new Map(),
  }
  render(
    <WorkbenchEventProvider tree={tree}>
      <HarnessChild paneIds={subscriptions} capture={capture} />
    </WorkbenchEventProvider>,
  )
  return capture
}

// ── Tests ─────────────────────────────────────────────────────

describe('WorkbenchEventBus routing', () => {
  it('routes open-doc to the focused DocPane when multiple exist', () => {
    const tree = tabs('g1', [
      { id: 'doc-A', type: 'doc' },
      { id: 'doc-B', type: 'doc' },
    ])
    const cap = renderHarness(tree, [
      { id: 'doc-A', event: 'open-doc' },
      { id: 'doc-B', event: 'open-doc' },
    ])

    act(() => {
      cap.bus.setFocusedPane('doc-B')
      cap.bus.emit('open-doc', { docId: 'X' })
    })

    expect(cap.received.get('doc-A') ?? []).toEqual([])
    expect(cap.received.get('doc-B')).toEqual([{ docId: 'X' }])
  })

  it('falls back to most-recently-focused DocPane when nothing is currently focused', () => {
    const tree = tabs('g1', [
      { id: 'doc-A', type: 'doc' },
      { id: 'doc-B', type: 'doc' },
    ])
    const cap = renderHarness(tree, [
      { id: 'doc-A', event: 'open-doc' },
      { id: 'doc-B', event: 'open-doc' },
    ])

    act(() => {
      cap.bus.setFocusedPane('doc-A') // most-recent
      cap.bus.setFocusedPane('doc-B') // current focus
      // Now simulate doc-B losing focus by re-focusing to a non-doc pane.
      // (No non-doc pane in tree → bus.setFocusedPane to a pane that doesn't
      // exist still records it in the LRU but won't match a routing target.)
      cap.bus.setFocusedPane('phantom')
      cap.bus.emit('open-doc', { docId: 'Y' })
    })

    // Phantom is "focused" but not a DocPane → fall back to LRU.
    // doc-B was focused most recently among doc panes → wins.
    expect(cap.received.get('doc-B')).toEqual([{ docId: 'Y' }])
    expect(cap.received.get('doc-A') ?? []).toEqual([])
  })

  it('falls back to first matching pane in tree order when LRU is empty', () => {
    const tree = tabs('g1', [
      { id: 'doc-A', type: 'doc' },
      { id: 'doc-B', type: 'doc' },
    ])
    const cap = renderHarness(tree, [
      { id: 'doc-A', event: 'open-doc' },
      { id: 'doc-B', event: 'open-doc' },
    ])

    act(() => {
      cap.bus.emit('open-doc', { docId: 'Z' })
    })

    expect(cap.received.get('doc-A')).toEqual([{ docId: 'Z' }])
    expect(cap.received.get('doc-B') ?? []).toEqual([])
  })

  it('shows a toast when no pane of the right type exists', () => {
    toastSpy.mockClear()
    const tree = tabs('g1', [{ id: 'tasks-A', type: 'tasks' }])
    const cap = renderHarness(tree, [])

    act(() => {
      cap.bus.emit('open-doc', { docId: 'X' })
    })

    expect(toastSpy).toHaveBeenCalledTimes(1)
    expect(toastSpy.mock.calls[0][0]).toMatch(/no doc pane is open/i)
  })

  it('shows a "tab inactive" toast when the target pane has no listener', () => {
    toastSpy.mockClear()
    // Tree contains a doc pane but the harness never subscribes — this
    // mimics an inactive tab whose pane component is unmounted.
    const tree = tabs('g1', [{ id: 'doc-A', type: 'doc' }])
    const cap = renderHarness(tree, [])

    act(() => {
      cap.bus.emit('open-doc', { docId: 'X' })
    })

    expect(toastSpy).toHaveBeenCalledTimes(1)
    expect(toastSpy.mock.calls[0][0]).toMatch(/inactive tab/i)
  })

  // ── open-task event + setFallback (Phase C2 D1-b) ────────────

  it('routes open-task to the focused TaskDetailPane when one exists', () => {
    const tree = tabs('g1', [
      { id: 'tasks-A', type: 'tasks' },
      { id: 'detail-A', type: 'task-detail' },
    ])
    const cap = renderHarness(tree, [
      { id: 'detail-A', event: 'open-task' },
    ])

    act(() => {
      cap.bus.emit('open-task', { taskId: 'task-123' })
    })

    expect(cap.received.get('detail-A')).toEqual([{ taskId: 'task-123' }])
  })

  it('invokes setFallback when no TaskDetailPane exists (slide-over path)', () => {
    toastSpy.mockClear()
    const fallbackSpy = vi.fn()
    const tree = tabs('g1', [{ id: 'tasks-A', type: 'tasks' }])
    const cap = renderHarness(tree, [])

    act(() => {
      cap.bus.setFallback('open-task', (payload) => fallbackSpy(payload))
      cap.bus.emit('open-task', { taskId: 'task-X' })
    })

    expect(fallbackSpy).toHaveBeenCalledTimes(1)
    expect(fallbackSpy.mock.calls[0][0]).toEqual({ taskId: 'task-X' })
    // Toast should NOT fire when fallback handles the event.
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('falls back to toast when no pane and no fallback registered', () => {
    toastSpy.mockClear()
    const tree = tabs('g1', [{ id: 'tasks-A', type: 'tasks' }])
    const cap = renderHarness(tree, [])

    act(() => {
      cap.bus.emit('open-task', { taskId: 'task-X' })
    })

    expect(toastSpy).toHaveBeenCalledTimes(1)
    expect(toastSpy.mock.calls[0][0]).toMatch(/no task detail pane/i)
  })

  it('setFallback returns an unsubscribe that removes only its own handler', () => {
    const tree = tabs('g1', [{ id: 'tasks-A', type: 'tasks' }])
    const cap = renderHarness(tree, [])
    const cb1 = vi.fn()
    const cb2 = vi.fn()
    let unsub1: () => void = () => {}

    act(() => {
      unsub1 = cap.bus.setFallback('open-task', cb1)
      cap.bus.setFallback('open-task', cb2) // overwrites cb1
    })
    act(() => {
      // unsub1 should be a no-op now (cb1 was already replaced).
      unsub1()
      cap.bus.emit('open-task', { taskId: 'task-Y' })
    })

    expect(cb1).not.toHaveBeenCalled()
    expect(cb2).toHaveBeenCalledTimes(1)
  })
})
