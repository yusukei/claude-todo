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

  it('P6: flush(projectId) PUTs that project immediately', async () => {
    let putCount = 0
    server.use(
      http.put('/api/v1/workbench/layouts/:projectId', () => {
        putCount += 1
        return HttpResponse.json({ updated_at: 'ts' })
      }),
    )
    const saver = makeServerSaver(10_000, () => 'tab-z')
    saver.save('proj', SAMPLE_TREE)
    saver.flush('proj')
    await Promise.resolve()
    await Promise.resolve()
    expect(putCount).toBe(1)
  })

  it('P6: cancel(projectId) drops the pending payload', async () => {
    let putCount = 0
    server.use(
      http.put('/api/v1/workbench/layouts/:projectId', () => {
        putCount += 1
        return HttpResponse.json({ updated_at: 'ts' })
      }),
    )
    const saver = makeServerSaver(50, () => 'tab-z')
    saver.save('proj', SAMPLE_TREE)
    saver.cancel('proj')
    await vi.advanceTimersByTimeAsync(200)
    await Promise.resolve()
    expect(putCount).toBe(0)
  })

  it('P6+ (v2): per-projectId queues are isolated — save(B) does NOT affect A pending', async () => {
    // 新設計: projectId 単位の独立 slot. A と B が互いに干渉しない.
    // 前 project の最終 layout は project 切替の unmount cleanup で
    // flush(projectId) する設計 (useWorkbenchStore の useEffect cleanup).
    const seenProjects: string[] = []
    server.use(
      http.put('/api/v1/workbench/layouts/:projectId', ({ params }) => {
        seenProjects.push(String(params.projectId))
        return HttpResponse.json({ updated_at: 'ts' })
      }),
    )
    const saver = makeServerSaver(100, () => 'tab-z')
    saver.save('proj-A', SAMPLE_TREE)
    saver.save('proj-B', SAMPLE_TREE)
    // 両方 debounce 中、PUT 未発火
    expect(seenProjects).toEqual([])
    await vi.advanceTimersByTimeAsync(101)
    await Promise.resolve()
    await Promise.resolve()
    // 同じ timer 経過で両方 fire (ほぼ同時にスケジュールされたため)
    expect(seenProjects.sort()).toEqual(['proj-A', 'proj-B'])
  })

  it('P6++ : flush(A) fires A only, leaves B pending intact', async () => {
    const seenProjects: string[] = []
    server.use(
      http.put('/api/v1/workbench/layouts/:projectId', ({ params }) => {
        seenProjects.push(String(params.projectId))
        return HttpResponse.json({ updated_at: 'ts' })
      }),
    )
    const saver = makeServerSaver(10_000, () => 'tab-z')
    saver.save('proj-A', SAMPLE_TREE)
    saver.save('proj-B', SAMPLE_TREE)
    saver.flush('proj-A') // A だけ即 fire
    await Promise.resolve()
    await Promise.resolve()
    expect(seenProjects).toEqual(['proj-A'])
    // B はまだ pending (timer 10s)
    await vi.advanceTimersByTimeAsync(100)
    await Promise.resolve()
    expect(seenProjects).toEqual(['proj-A'])
    // flush(B) で fire
    saver.flush('proj-B')
    await Promise.resolve()
    await Promise.resolve()
    expect(seenProjects).toEqual(['proj-A', 'proj-B'])
  })

  it('P6+++ : flushAll() fires all pending PUTs', async () => {
    const seen: string[] = []
    server.use(
      http.put('/api/v1/workbench/layouts/:projectId', ({ params }) => {
        seen.push(String(params.projectId))
        return HttpResponse.json({ updated_at: 'ts' })
      }),
    )
    const saver = makeServerSaver(10_000, () => 'tab-z')
    saver.save('proj-A', SAMPLE_TREE)
    saver.save('proj-B', SAMPLE_TREE)
    saver.save('proj-C', SAMPLE_TREE)
    saver.flushAll()
    await Promise.resolve()
    await Promise.resolve()
    expect(seen.sort()).toEqual(['proj-A', 'proj-B', 'proj-C'])
  })

  it('P6++++: cancel(A) leaves B pending intact', async () => {
    const seen: string[] = []
    server.use(
      http.put('/api/v1/workbench/layouts/:projectId', ({ params }) => {
        seen.push(String(params.projectId))
        return HttpResponse.json({ updated_at: 'ts' })
      }),
    )
    const saver = makeServerSaver(100, () => 'tab-z')
    saver.save('proj-A', SAMPLE_TREE)
    saver.save('proj-B', SAMPLE_TREE)
    saver.cancel('proj-A')
    await vi.advanceTimersByTimeAsync(101)
    await Promise.resolve()
    await Promise.resolve()
    expect(seen).toEqual(['proj-B'])
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
