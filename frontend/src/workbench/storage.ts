/**
 * Persist a Workbench layout to localStorage with schema versioning,
 * corruption recovery, and last-write-wins reconciliation across
 * browser tabs.
 */
import { showErrorToast } from '../components/common/Toast'
import type { LayoutTree, PaneType, PersistedLayout } from './types'
import { LAYOUT_SCHEMA_VERSION } from './types'
import {
  defaultLayout,
  normaliseTree,
  sanitiseUnknownPaneTypes,
  validateTree,
} from './treeUtils'

const KEY_PREFIX = 'workbench:layout:'
const CORRUPT_PREFIX_SUFFIX = ':corrupt-'
const CLIENT_ID_KEY = 'workbench:clientId'

const layoutKey = (projectId: string): string =>
  `${KEY_PREFIX}${projectId}`

/** Stable per-tab identifier used by the server-side sync to filter
 *  out a client's own SSE echo. Lives in ``sessionStorage`` so it
 *  survives reloads of the same tab but is unique across tabs. The
 *  fallback when ``crypto.randomUUID`` is unavailable is a 32-char
 *  hex string built from ``Math.random`` — collision risk is purely
 *  cosmetic (echo suppression vs. a redundant refetch). */
export function getOrCreateClientId(): string {
  try {
    const existing = window.sessionStorage.getItem(CLIENT_ID_KEY)
    if (existing) return existing
    const fresh = generateUuid()
    window.sessionStorage.setItem(CLIENT_ID_KEY, fresh)
    return fresh
  } catch {
    // Privacy mode / disabled storage — fall back to a process-local
    // value so echo suppression still works for the lifetime of this
    // page (lost on reload, which is the same as no suppression).
    return generateUuid()
  }
}

function generateUuid(): string {
  const c = (typeof crypto !== 'undefined' ? crypto : null) as
    | (Crypto & { randomUUID?: () => string })
    | null
  if (c?.randomUUID) return c.randomUUID()
  // RFC 4122 v4-ish fallback. Good enough for echo-suppression keys.
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (ch) => {
    const r = (Math.random() * 16) | 0
    const v = ch === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

/** Load + validate the stored layout. On any corruption (parse
 *  error, schema version mismatch, structural validation failure)
 *  the bad blob is moved to ``...:corrupt-{ts}`` and the function
 *  returns the default layout so the user is never locked out of
 *  their Workbench.
 */
export function loadLayout(
  projectId: string,
  knownPaneTypes: Set<PaneType>,
): LayoutTree {
  const key = layoutKey(projectId)
  const raw = safeGetItem(key)
  if (!raw) return defaultLayout()

  const fallback = (reason: string): LayoutTree => {
    quarantine(key, raw, reason)
    showErrorToast(
      `Workbench layout could not be loaded (${reason}). ` +
      'Restored to default. The corrupt data is preserved in ' +
      'localStorage under a "...:corrupt-" key.',
    )
    return defaultLayout()
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch (e) {
    return fallback(`JSON parse error: ${(e as Error).message}`)
  }

  if (
    !parsed ||
    typeof parsed !== 'object' ||
    (parsed as PersistedLayout).version !== LAYOUT_SCHEMA_VERSION
  ) {
    return fallback(
      `unsupported schema version (got ${(parsed as { version?: unknown })?.version})`,
    )
  }

  const tree = (parsed as PersistedLayout).tree
  const validationErr = validateTree(tree)
  if (validationErr) return fallback(`structural error: ${validationErr}`)

  return normaliseTree(sanitiseUnknownPaneTypes(tree, knownPaneTypes))
}

/** Save a layout. Always writes a fresh ``savedAt`` timestamp so
 *  cross-tab listeners can resolve last-write-wins. */
export function saveLayout(projectId: string, tree: LayoutTree): void {
  const payload: PersistedLayout = {
    version: LAYOUT_SCHEMA_VERSION,
    savedAt: Date.now(),
    tree,
  }
  safeSetItem(layoutKey(projectId), JSON.stringify(payload))
}

/** Returns a debounced version of ``saveLayout``. The caller owns
 *  the timer (via the returned ``cancel`` function) so component
 *  unmount can cancel a pending write that would otherwise resurrect
 *  stale state on a fast remount. */
export function makeDebouncedSaver(
  delayMs: number,
): {
  save: (projectId: string, tree: LayoutTree) => void
  flush: () => void
  cancel: () => void
} {
  let timer: ReturnType<typeof setTimeout> | null = null
  let pending: { projectId: string; tree: LayoutTree } | null = null
  const flush = () => {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
    if (pending) {
      saveLayout(pending.projectId, pending.tree)
      pending = null
    }
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
    timer = setTimeout(flush, delayMs)
  }
  return { save, flush, cancel }
}

/** Subscribe to ``storage`` events from other tabs that share this
 *  origin, surfacing only those that target ``projectId``'s layout
 *  key. The callback receives the parsed (and validated) tree, never
 *  raw JSON. Last-write-wins: the caller compares ``savedAt`` and
 *  only adopts newer writes. */
export function subscribeCrossTab(
  projectId: string,
  knownPaneTypes: Set<PaneType>,
  onUpdate: (tree: LayoutTree, savedAt: number) => void,
): () => void {
  const key = layoutKey(projectId)
  const handler = (e: StorageEvent) => {
    if (e.key !== key || !e.newValue) return
    try {
      const parsed = JSON.parse(e.newValue) as PersistedLayout
      if (parsed.version !== LAYOUT_SCHEMA_VERSION) return
      const err = validateTree(parsed.tree)
      if (err) return
      const sanitised = normaliseTree(
        sanitiseUnknownPaneTypes(parsed.tree, knownPaneTypes),
      )
      onUpdate(sanitised, parsed.savedAt)
    } catch {
      // Ignore: another tab wrote garbage. The user-facing toast on
      // the writing tab already alerted the operator.
    }
  }
  window.addEventListener('storage', handler)
  return () => window.removeEventListener('storage', handler)
}

// ── Internal helpers ──────────────────────────────────────────

function safeGetItem(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function safeSetItem(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value)
  } catch (e) {
    // Quota / privacy mode / disabled storage. Nothing to do — the
    // Workbench keeps working in-memory.
    console.warn('[workbench] localStorage write failed:', e)
  }
}

function quarantine(key: string, raw: string, reason: string): void {
  try {
    const stamp = Date.now()
    window.localStorage.setItem(
      `${key}${CORRUPT_PREFIX_SUFFIX}${stamp}`,
      JSON.stringify({ reason, raw, stamp }),
    )
    window.localStorage.removeItem(key)
  } catch {
    // localStorage write failed — nothing further to do; we'll fall
    // back to the default layout this session.
  }
}
