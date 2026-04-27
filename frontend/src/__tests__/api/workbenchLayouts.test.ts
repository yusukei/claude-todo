/**
 * Workbench layout API client wrappers (P2 - P7).
 *
 * Tests cover:
 *   - getServerLayout: 404 → null, 200 → payload
 *   - putServerLayout: body shape
 *   - makeServerSaver: debounce, flush, cancel, onSaved callback
 *   - beaconLayout: navigator.sendBeacon target URL + body
 */
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { server } from '../mocks/server'
import {
  beaconLayout,
  getServerLayout,
  makeServerSaver,
  putServerLayout,
} from '../../api/workbenchLayouts'
import type { LayoutTree } from '../../workbench/types'

const SAMPLE_TREE: LayoutTree = {
  kind: 'tabs',
  id: 'g1',
  tabs: [{ id: 'p1', paneType: 'tasks', paneConfig: {} }],
  activeTabId: 'p1',
}

describe('Workbench / Persistence — P2/P3: getServerLayout', () => {
  it('P2: returns null on 404', async () => {
    server.use(
      http.get('/api/v1/workbench/layouts/:projectId', () =>
        HttpResponse.json({ detail: 'not found' }, { status: 404 }),
      ),
    )
    const r = await getServerLayout('proj-x')
    expect(r).toBeNull()
  })

  it('P3: returns the server JSON on 200', async () => {
    server.use(
      http.get('/api/v1/workbench/layouts/:projectId', () =>
        HttpResponse.json({
          tree: SAMPLE_TREE,
          schema_version: 1,
          client_id: 'tab-123',
          updated_at: '2026-04-26T00:00:00+00:00',
        }),
      ),
    )
    const r = await getServerLayout('proj-x')
    expect(r).not.toBeNull()
    expect(r!.tree).toEqual(SAMPLE_TREE)
    expect(r!.client_id).toBe('tab-123')
  })

  it('non-404 errors propagate', async () => {
    server.use(
      http.get('/api/v1/workbench/layouts/:projectId', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )
    await expect(getServerLayout('proj-x')).rejects.toBeTruthy()
  })
})

describe('Workbench / Persistence — P4: putServerLayout body shape', () => {
  it('sends tree + schema_version + client_id', async () => {
    let received: unknown = null
    server.use(
      http.put('/api/v1/workbench/layouts/:projectId', async ({ request }) => {
        received = await request.json()
        return HttpResponse.json({ updated_at: '2026-04-26T00:00:00+00:00' })
      }),
    )
    await putServerLayout('proj-x', {
      tree: SAMPLE_TREE,
      schema_version: 1,
      client_id: 'tab-z',
    })
    expect(received).toEqual({
      tree: SAMPLE_TREE,
      schema_version: 1,
      client_id: 'tab-z',
    })
  })

  it('returns the response updated_at', async () => {
    server.use(
      http.put('/api/v1/workbench/layouts/:projectId', () =>
        HttpResponse.json({ updated_at: '2026-04-26T01:23:45+00:00' }),
      ),
    )
    const r = await putServerLayout('proj-x', {
      tree: SAMPLE_TREE,
      schema_version: 1,
      client_id: 'tab-z',
    })
    expect(r.updated_at).toBe('2026-04-26T01:23:45+00:00')
  })
})

describe('Workbench / Persistence — P5/P6: makeServerSaver', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('P5: debounces multiple save() calls into a single PUT', async () => {
    let putCount = 0
    server.use(
      http.put('/api/v1/workbench/layouts/:projectId', () => {
        putCount += 1
        return HttpResponse.json({ updated_at: 'ts' })
      }),
    )
    const saver = makeServerSaver(100, () => 'tab-z')
    saver.save('proj', SAMPLE_TREE)
    saver.save('proj', SAMPLE_TREE)
    saver.save('proj', SAMPLE_TREE)
    await vi.advanceTimersByTimeAsync(99)
    expect(putCount).toBe(0)
    await vi.advanceTimersByTimeAsync(2)
    // microtask drain
    await Promise.resolve()
    await Promise.resolve()
    expect(putCount).toBe(1)
  })

  it('P5: onSaved fires with the response updated_at', async () => {
    server.use(
      http.put('/api/v1/workbench/layouts/:projectId', () =>
        HttpResponse.json({ updated_at: '2026-04-26T05:00:00+00:00' }),
      ),
    )
    const onSaved = vi.fn()
    const saver = makeServerSaver(50, () => 'tab-z', onSaved)
    saver.save('proj', SAMPLE_TREE)
    await vi.advanceTimersByTimeAsync(60)
    await Promise.resolve()
    await Promise.resolve()
    expect(onSaved).toHaveBeenCalledWith('2026-04-26T05:00:00+00:00')
  })

  it('P6: flush() PUTs immediately', async () => {
    let putCount = 0
    server.use(
      http.put('/api/v1/workbench/layouts/:projectId', () => {
        putCount += 1
        return HttpResponse.json({ updated_at: 'ts' })
      }),
    )
    const saver = makeServerSaver(10_000, () => 'tab-z')
    saver.save('proj', SAMPLE_TREE)
    saver.flush()
    await Promise.resolve()
    await Promise.resolve()
    expect(putCount).toBe(1)
  })

  it('P6: cancel() drops the pending payload', async () => {
    let putCount = 0
    server.use(
      http.put('/api/v1/workbench/layouts/:projectId', () => {
        putCount += 1
        return HttpResponse.json({ updated_at: 'ts' })
      }),
    )
    const saver = makeServerSaver(50, () => 'tab-z')
    saver.save('proj', SAMPLE_TREE)
    saver.cancel()
    await vi.advanceTimersByTimeAsync(200)
    await Promise.resolve()
    expect(putCount).toBe(0)
  })

  it('P6+: switching projectId fires the prior pending PUT immediately', async () => {
    // Bug fix: 別 projectId の save が来たら前 project の最終 PUT を
    // 確実に流す。debounce 上書きで前 project の server save が消えるのを防ぐ。
    const seenProjects: string[] = []
    server.use(
      http.put('/api/v1/workbench/layouts/:projectId', ({ params }) => {
        seenProjects.push(String(params.projectId))
        return HttpResponse.json({ updated_at: 'ts' })
      }),
    )
    const saver = makeServerSaver(100, () => 'tab-z')
    saver.save('proj-A', SAMPLE_TREE)
    // この時点では未 PUT (debounce 中)
    expect(seenProjects).toEqual([])
    // 別 projectId の save → A の pending が即時 fire
    saver.save('proj-B', SAMPLE_TREE)
    await Promise.resolve()
    await Promise.resolve()
    expect(seenProjects).toEqual(['proj-A'])
    // B は debounce 中、まだ PUT されない
    await vi.advanceTimersByTimeAsync(101)
    await Promise.resolve()
    await Promise.resolve()
    expect(seenProjects).toEqual(['proj-A', 'proj-B'])
  })
})

describe('Workbench / Persistence — P7: beaconLayout', () => {
  let originalSendBeacon: typeof navigator.sendBeacon | undefined
  beforeEach(() => {
    originalSendBeacon = navigator.sendBeacon
  })
  afterEach(() => {
    if (originalSendBeacon) {
      Object.defineProperty(navigator, 'sendBeacon', {
        value: originalSendBeacon,
        configurable: true,
      })
    }
  })

  it('calls navigator.sendBeacon against the /beacon URL with a JSON Blob', () => {
    const calls: Array<{ url: string; data: BodyInit | null }> = []
    Object.defineProperty(navigator, 'sendBeacon', {
      value: vi.fn((url: string, data?: BodyInit | null) => {
        calls.push({ url, data: data ?? null })
        return true
      }),
      configurable: true,
    })

    beaconLayout('proj-abc', {
      tree: SAMPLE_TREE,
      schema_version: 1,
      client_id: 'tab-z',
    })

    expect(calls).toHaveLength(1)
    expect(calls[0].url).toBe('/api/v1/workbench/layouts/proj-abc/beacon')
    expect(calls[0].data).toBeInstanceOf(Blob)
  })

  it('is a no-op when sendBeacon is unavailable', () => {
    Object.defineProperty(navigator, 'sendBeacon', {
      value: undefined,
      configurable: true,
    })
    expect(() =>
      beaconLayout('proj', {
        tree: SAMPLE_TREE,
        schema_version: 1,
        client_id: 't',
      }),
    ).not.toThrow()
  })
})
