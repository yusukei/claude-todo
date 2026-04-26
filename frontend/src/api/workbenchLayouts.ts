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

/** Returns a debounced server-side saver. Caller owns the timer via
 *  ``cancel`` so unmount can drop a pending write whose state will
 *  no longer be authoritative. ``flush`` triggers an immediate PUT
 *  for the most recent pending payload (used on visibility-hidden so
 *  the server has the fresh layout when the user switches tabs).
 *
 *  The PUT response's ``updated_at`` is reported via ``onSaved`` so
 *  the caller can advance its echo-suppression cursor without coupling
 *  this saver to a specific React ref shape. */
export function makeServerSaver(
  delayMs: number,
  getClientId: () => string,
  onSaved?: (updatedAt: string) => void,
): {
  save: (projectId: string, tree: LayoutTree) => void
  flush: () => void
  cancel: () => void
} {
  let timer: ReturnType<typeof setTimeout> | null = null
  let pending: { projectId: string; tree: LayoutTree } | null = null

  const fire = async () => {
    if (!pending) return
    const { projectId, tree } = pending
    pending = null
    try {
      const r = await putServerLayout(projectId, {
        tree,
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

  const flush = () => {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
    void fire()
  }

  const cancel = () => {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
    pending = null
  }

  const save = (projectId: string, tree: LayoutTree) => {
    pending = { projectId, tree }
    if (timer !== null) clearTimeout(timer)
    timer = setTimeout(() => {
      timer = null
      void fire()
    }, delayMs)
  }

  return { save, flush, cancel }
}
