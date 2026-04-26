/**
 * TerminalView reattach behavior (T1 - T7).
 *
 * These tests stub the API client and the global WebSocket so the
 * component's setup() can run without a real network. The xterm
 * ``Terminal`` is mocked so we can spy on `write`, `writeln`, and
 * `onData` registration.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '../mocks/server'

// ── xterm.js mocks ──────────────────────────────────────────────
//
// We capture the most-recent Terminal instance per test so the
// assertions can interrogate writes. The mock implements just the
// surface TerminalView touches.

interface MockTerm {
  write: ReturnType<typeof vi.fn>
  writeln: ReturnType<typeof vi.fn>
  onData: ReturnType<typeof vi.fn>
  loadAddon: ReturnType<typeof vi.fn>
  open: ReturnType<typeof vi.fn>
  dispose: ReturnType<typeof vi.fn>
  cols: number
  rows: number
  parser: { registerCsiHandler: ReturnType<typeof vi.fn> }
  buffer: unknown
  // Captured handler so tests can simulate xterm-emitted onData
  // (e.g. DA response during scrollback replay).
  _onDataHandler?: (data: string) => void
  // Pending write callbacks so a test can release them at a chosen
  // moment (used for T3 where the gate must still be active when
  // we simulate xterm firing onData).
  _pendingWriteCbs: Array<() => void>
}

let lastTerm: MockTerm | null = null
let autoFlushWriteCbs = true

function makeMockTerm(): MockTerm {
  const t: MockTerm = {
    write: vi.fn(),
    writeln: vi.fn(),
    onData: vi.fn(),
    loadAddon: vi.fn(),
    open: vi.fn(),
    dispose: vi.fn(),
    cols: 80,
    rows: 24,
    parser: {
      registerCsiHandler: vi.fn(() => ({ dispose: vi.fn() })),
    },
    _pendingWriteCbs: [],
    // PredictiveEngine.onUserInput pokes into terminal.buffer.active —
    // a minimal stub keeps it from crashing in jsdom.
    buffer: {
      active: { cursorX: 0, cursorY: 0 },
    } as unknown,
  } as unknown as MockTerm
  t.write.mockImplementation((_data: string, cb?: () => void) => {
    if (cb) {
      if (autoFlushWriteCbs) {
        cb()
      } else {
        t._pendingWriteCbs.push(cb)
      }
    }
  })
  t.onData.mockImplementation((handler: (data: string) => void) => {
    t._onDataHandler = handler
    return { dispose: vi.fn() }
  })
  return t
}

vi.mock('@xterm/xterm', () => ({
  Terminal: vi.fn().mockImplementation(() => {
    const t = makeMockTerm()
    lastTerm = t
    return t
  }),
}))

vi.mock('@xterm/addon-fit', () => ({
  FitAddon: vi.fn().mockImplementation(() => ({
    fit: vi.fn(),
  })),
}))

vi.mock('@xterm/addon-webgl', () => ({
  WebglAddon: vi.fn().mockImplementation(() => ({
    onContextLoss: vi.fn(),
    dispose: vi.fn(),
  })),
}))

// ── WebSocket mock ──────────────────────────────────────────────

interface MockWS {
  readyState: number
  send: ReturnType<typeof vi.fn>
  close: ReturnType<typeof vi.fn>
  onopen: ((ev?: unknown) => void) | null
  onmessage: ((ev: { data: string }) => void) | null
  onclose: ((ev: { reason: string; code: number }) => void) | null
  onerror: ((ev?: unknown) => void) | null
}

let lastWS: MockWS | null = null

beforeEach(() => {
  lastTerm = null
  lastWS = null
  autoFlushWriteCbs = true
  // ResizeObserver is not in jsdom by default.
  if (!('ResizeObserver' in globalThis)) {
    ;(globalThis as { ResizeObserver?: unknown }).ResizeObserver =
      vi.fn().mockImplementation(() => ({
        observe: vi.fn(),
        disconnect: vi.fn(),
      }))
  }
  // Stub WebSocket via vi.stubGlobal so jsdom's read-only global
  // descriptor doesn't reject the override.
  const WSMock = vi.fn().mockImplementation(() => {
    const ws: MockWS = {
      readyState: 1, // WebSocket.OPEN
      send: vi.fn(),
      close: vi.fn(),
      onopen: null,
      onmessage: null,
      onclose: null,
      onerror: null,
    }
    lastWS = ws
    Promise.resolve().then(() => ws.onopen?.())
    return ws
  }) as unknown as typeof WebSocket
  ;(WSMock as unknown as { OPEN: number }).OPEN = 1
  vi.stubGlobal('WebSocket', WSMock)
  server.use(
    http.post('/api/v1/workspaces/terminal/ticket', () =>
      HttpResponse.json({ ticket: 'tkt' }),
    ),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// Helper: render TerminalView with the given sessionId, await ws
// onopen, then deliver a session_started message.
async function renderAndAttach(opts: {
  sessionId?: string
  attached?: boolean
  scrollback?: string[]
  exited?: boolean
}) {
  const { default: TerminalView } = await import('../../components/workspace/TerminalView')
  render(<TerminalView agentId="agent-1" sessionId={opts.sessionId} />)
  // Wait for the async setup() to create the terminal + ws and
  // register listeners.
  await new Promise<void>((resolve) => setTimeout(resolve, 0))
  // ticket fetch + ws open
  await new Promise<void>((resolve) => setTimeout(resolve, 0))
  // Now deliver session_started
  if (lastWS?.onmessage) {
    lastWS.onmessage({
      data: JSON.stringify({
        type: 'session_started',
        session_id: opts.sessionId ?? 'sess-new',
        attached: opts.attached ?? false,
        scrollback: opts.scrollback ?? [],
        exited: opts.exited ?? false,
      }),
    })
  }
  // Allow the terminal.write callback (microtask) to fire.
  await Promise.resolve()
  await Promise.resolve()
}

describe('Workbench / TerminalView reattach — T1: scrollback is replayed', () => {
  it('writes scrollback chunks to xterm when attached=true', async () => {
    await renderAndAttach({
      sessionId: 'existing',
      attached: true,
      scrollback: ['hello\r\n', 'world\r\n'],
    })
    expect(lastTerm).not.toBeNull()
    // At least one write call carried the scrollback content.
    const allWrites = (lastTerm!.write.mock.calls as Array<[string, ...unknown[]]>)
      .map((c) => c[0])
      .join('')
    expect(allWrites).toContain('hello')
    expect(allWrites).toContain('world')
  })
})

describe('Workbench / TerminalView reattach — T2: scrollback is batched into one write', () => {
  it('calls terminal.write at most once for the scrollback payload (single combined write)', async () => {
    await renderAndAttach({
      sessionId: 'existing',
      attached: true,
      scrollback: ['a', 'b', 'c', 'd', 'e'],
    })
    // Allow other write calls (clear, etc.) but the scrollback chunks
    // themselves must be coalesced into ONE call carrying "abcde".
    const writes = (lastTerm!.write.mock.calls as Array<[string, ...unknown[]]>).map(
      (c) => c[0],
    )
    const matchingWrites = writes.filter((w) => w.includes('abcde'))
    expect(matchingWrites).toHaveLength(1)
  })
})

describe('Workbench / TerminalView reattach — T3/T4: onData is gated during replay', () => {
  it('T3: does NOT forward xterm-emitted onData to the WebSocket while scrollback is being parsed', async () => {
    // Hold write callbacks open so the gate stays raised until we
    // manually release.
    autoFlushWriteCbs = false
    await renderAndAttach({
      sessionId: 'existing',
      attached: true,
      scrollback: ['banner output'],
    })
    const sendBeforeCount = lastWS!.send.mock.calls.length
    // Simulate xterm responding to a DA1 query (\x1b[c) it found in
    // the scrollback. The mock fires the captured onData handler.
    lastTerm!._onDataHandler?.('\x1b[?1;2c')
    const newSends = lastWS!.send.mock.calls
      .slice(sendBeforeCount)
      .map((c) => JSON.parse(c[0] as string))
      .filter((m) => m.type === 'input')
    expect(newSends).toHaveLength(0)
  })

  it('T4: live keystrokes after replay completes ARE forwarded', async () => {
    autoFlushWriteCbs = false
    await renderAndAttach({
      sessionId: 'existing',
      attached: true,
      scrollback: ['x'],
    })
    // Release the deferred callback, then wait for the rAF that lifts
    // the gate.
    lastTerm!._pendingWriteCbs.forEach((cb) => cb())
    await new Promise<void>((r) => setTimeout(r, 32))
    const sendBeforeCount = lastWS!.send.mock.calls.length
    lastTerm!._onDataHandler?.('A')
    const newSends = lastWS!.send.mock.calls
      .slice(sendBeforeCount)
      .map((c) => JSON.parse(c[0] as string))
      .filter((m) => m.type === 'input' && m.data === 'A')
    expect(newSends.length).toBeGreaterThan(0)
  })
})

describe('Workbench / TerminalView reattach — T5/T6: no banner is written', () => {
  it('does NOT writeln "[reattached]"', async () => {
    await renderAndAttach({
      sessionId: 'existing',
      attached: true,
      scrollback: ['x'],
      exited: false,
    })
    const writelnArgs = (lastTerm!.writeln.mock.calls as string[][]).flat()
    const writeArgs = (lastTerm!.write.mock.calls as Array<[string, ...unknown[]]>).map(
      (c) => c[0],
    )
    const all = [...writelnArgs, ...writeArgs].join('\n')
    expect(all).not.toMatch(/\[reattached\]/)
    expect(all).not.toMatch(/\[reattached to an exited session/)
  })

  it('does NOT writeln read-only banner even when exited=true', async () => {
    await renderAndAttach({
      sessionId: 'existing',
      attached: true,
      scrollback: ['x'],
      exited: true,
    })
    const writelnArgs = (lastTerm!.writeln.mock.calls as string[][]).flat()
    const writeArgs = (lastTerm!.write.mock.calls as Array<[string, ...unknown[]]>).map(
      (c) => c[0],
    )
    const all = [...writelnArgs, ...writeArgs].join('\n')
    expect(all).not.toMatch(/read-only/)
    expect(all).not.toMatch(/\[reattached/)
  })
})

describe('Workbench / TerminalView reattach — T7: fresh session does not replay', () => {
  it('skips scrollback when attached=false', async () => {
    await renderAndAttach({
      attached: false,
      scrollback: ['SHOULD-NOT-APPEAR'],
    })
    const writes = (lastTerm!.write.mock.calls as Array<[string, ...unknown[]]>).map(
      (c) => c[0],
    )
    expect(writes.join('')).not.toContain('SHOULD-NOT-APPEAR')
  })
})
