import { api } from './client'
import type { LayoutTree } from '../workbench/types'
import { LAYOUT_SCHEMA_VERSION } from '../workbench/types'

export interface ServerLayoutPayload {
  tree: LayoutTree
  schema_version: number
  client_id: string
  updated_at: string
}

interface PutResponse {
  updated_at: string
}

/** Fetch the user's layout for ``projectId``. Returns ``null`` when
 *  the server has no layout stored yet (404). All other failures
 *  bubble up so the caller can decide how to fall back. */
export async function getServerLayout(
  projectId: string,
  signal?: AbortSignal,
): Promise<ServerLayoutPayload | null> {
  try {
    const r = await api.get<ServerLayoutPayload>(
      `/workbench/layouts/${projectId}`,
      { signal },
    )
    return r.data
  } catch (e) {
    if ((e as { response?: { status?: number } })?.response?.status === 404) {
      return null
    }
    throw e
  }
}

export async function putServerLayout(
  projectId: string,
  body: { tree: LayoutTree; schema_version: number; client_id: string },
): Promise<PutResponse> {
  const r = await api.put<PutResponse>(`/workbench/layouts/${projectId}`, body)
  return r.data
}

/** Best-effort synchronous-ish flush for ``beforeunload`` / ``pagehide``.
 *  Falls back silently when ``sendBeacon`` is unavailable or rejects
 *  the payload (size cap / disabled). The page is being torn down so
 *  there's nothing actionable for the caller to do with a failure. */
export function beaconLayout(
  projectId: string,
  body: { tree: LayoutTree; schema_version: number; client_id: string },
): void {
  if (typeof navigator === 'undefined' || !navigator.sendBeacon) return
  try {
    const blob = new Blob([JSON.stringify(body)], { type: 'application/json' })
    // sendBeacon does not support custom verbs; the server PUT endpoint
    // accepts POST as well via a small alias to support this path.
    // (See backend workbench_layouts.py.)
    navigator.sendBeacon(
      `/api/v1/workbench/layouts/${encodeURIComponent(projectId)}/beacon`,
      blob,
    )
  } catch {
    // Beacon is opportunistic; ignore failures.
  }
}

/** Per-projectId debounced server-side saver.
 *
 *  v1 では module-level の **単一 pending** で複数 projectId を扱って
 *  いた (project 跨ぎで pending 上書き race の温床)。 v2 では
 *  ``Map<projectId, slot>`` を持ち、各 project ごとに独立した
 *  pending + timer を維持する。これにより:
 *
 *    - 異なる projectId の save は互いに干渉しない
 *    - flush(projectId) で 1 つだけ即時 PUT できる (project 切替時の
 *      unmount-flush に必須)
 *    - cancel(projectId) で 1 つだけ捨てられる (beacon 経由で代替送信
 *      する場合)
 *    - flushAll() で全 pending を fire (visibility hidden 等)
 *
 *  ``onSaved`` は PUT 成功時に updated_at を伝える共通 hook。
 */
export function makeServerSaver(
  delayMs: number,
  getClientId: () => string,
  onSaved?: (updatedAt: string) => void,
): {
  save: (projectId: string, tree: LayoutTree) => void
  flush: (projectId: string) => void
  flushAll: () => void
  cancel: (projectId: string) => void
  cancelAll: () => void
} {
  interface Slot {
    pending: LayoutTree
    timer: ReturnType<typeof setTimeout>
  }
  const slots = new Map<string, Slot>()

  const fire = async (projectId: string): Promise<void> => {
    const slot = slots.get(projectId)
    if (!slot) return
    // delete first so a concurrent save() can replace freely.
    slots.delete(projectId)
    try {
      const r = await putServerLayout(projectId, {
        tree: slot.pending,
        schema_version: LAYOUT_SCHEMA_VERSION,
        client_id: getClientId(),
      })
      onSaved?.(r.updated_at)
    } catch (e) {
      // Network / 5xx — leave the local cache in place; the next
      // mutation reschedules a save, and the unload beacon is the
      // last-ditch flush. Surface to the console so a real outage
      // is visible to operators.
      // eslint-disable-next-line no-console
      console.warn('[workbench] server layout save failed:', e)
    }
  }

  const save = (projectId: string, tree: LayoutTree) => {
    const existing = slots.get(projectId)
    if (existing) clearTimeout(existing.timer)
    const timer = setTimeout(() => {
      void fire(projectId)
    }, delayMs)
    slots.set(projectId, { pending: tree, timer })
  }

  const flush = (projectId: string) => {
    const slot = slots.get(projectId)
    if (!slot) return
    clearTimeout(slot.timer)
    void fire(projectId)
  }

  const flushAll = () => {
    for (const projectId of [...slots.keys()]) flush(projectId)
  }

  const cancel = (projectId: string) => {
    const slot = slots.get(projectId)
    if (slot) {
      clearTimeout(slot.timer)
      slots.delete(projectId)
    }
  }

  const cancelAll = () => {
    for (const slot of slots.values()) clearTimeout(slot.timer)
    slots.clear()
  }

  return { save, flush, flushAll, cancel, cancelAll }
}
