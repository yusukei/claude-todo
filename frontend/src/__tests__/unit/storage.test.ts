/**
 * Workbench storage primitives — loadLayout, saveLayout,
 * makeDebouncedSaver, subscribeCrossTab.
 *
 * Invariants (S-prefix to avoid collision with the sidebar S series):
 *   ST1  loadLayout returns the default layout when the key is absent
 *   ST2  loadLayout returns the parsed tree on a valid payload
 *   ST3  loadLayout quarantines malformed JSON to ``...:corrupt-{ts}``
 *        and returns the default layout
 *   ST4  loadLayout quarantines a payload with a wrong schema version
 *   ST5  loadLayout quarantines a payload that fails structural validation
 *   ST6  saveLayout writes a versioned payload with savedAt + tree
 *   ST7  saveLayout swallows quota errors (storage write throws → no
 *        exception bubbles to the caller)
 *   ST8  makeDebouncedSaver: save→save→save fires once after delay
 *   ST9  makeDebouncedSaver.flush writes pending immediately
 *   ST10 makeDebouncedSaver.cancel drops the pending payload
 *   ST11 subscribeCrossTab notifies on a matching storage event
 *   ST12 subscribeCrossTab ignores events for a different project
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  __resetCrossTabSnapshotsForTesting,
  getCrossTabSnapshot,
  loadLayout,
  makeDebouncedSaver,
  saveLayout,
  subscribeCrossTab,
} from '../../workbench/storage'
import {
  LAYOUT_SCHEMA_VERSION,
  type LayoutTree,
  type PaneType,
} from '../../workbench/types'

/**
 * Match the shape of ``defaultLayout()`` without comparing the
 * randomly-generated node IDs (each call produces a fresh UUID).
 */
function expectIsDefaultLayout(tree: LayoutTree): void {
  expect(tree.kind).toBe('tabs')
  if (tree.kind !== 'tabs') return
  expect(tree.tabs.length).toBe(1)
  expect(tree.tabs[0].paneType).toBe('tasks')
  expect(tree.activeTabId).toBe(tree.tabs[0].id)
}

const PROJECT = 'proj-123'
const KEY = `workbench:layout:${PROJECT}`
const KNOWN: Set<PaneType> = new Set([
  'tasks',
  'task-detail',
  'terminal',
  'doc',
  'documents',
  'file-browser',
  'error-tracker',
  'unsupported',
])

const VALID_TREE: LayoutTree = {
  kind: 'tabs',
  id: 'g-test',
  tabs: [{ id: 'p-test', paneType: 'tasks', paneConfig: {} }],
  activeTabId: 'p-test',
}

afterEach(() => {
  // The afterEach in setup.ts already clears localStorage; this is
  // belt-and-suspenders for cases where the test added other keys
  // (e.g. quarantine entries).
  for (let i = window.localStorage.length - 1; i >= 0; i--) {
    const k = window.localStorage.key(i)
    if (k) window.localStorage.removeItem(k)
  }
})

describe('Workbench / Storage — ST1: loadLayout returns default when no entry', () => {
  it('returns the default layout when localStorage has no entry for the project', () => {
    const tree = loadLayout(PROJECT, KNOWN)
    expectIsDefaultLayout(tree)
  })
})

describe('Workbench / Storage — ST2: loadLayout returns parsed tree', () => {
  it('returns the stored tree when the payload is valid', () => {
    saveLayout(PROJECT, VALID_TREE)
    const tree = loadLayout(PROJECT, KNOWN)
    expect(tree).toEqual(VALID_TREE)
  })
})

describe('Workbench / Storage — ST3: loadLayout quarantines malformed JSON', () => {
  it('moves bad JSON to a corrupt key and returns the default layout', () => {
    window.localStorage.setItem(KEY, '{ this is not valid json')
    const tree = loadLayout(PROJECT, KNOWN)
    expectIsDefaultLayout(tree)
    // Corrupt key should now exist; original key cleared.
    expect(window.localStorage.getItem(KEY)).toBeNull()
    const corruptKeys: string[] = []
    for (let i = 0; i < window.localStorage.length; i++) {
      const k = window.localStorage.key(i)
      if (k && k.startsWith(`${KEY}:corrupt-`)) corruptKeys.push(k)
    }
    expect(corruptKeys.length).toBeGreaterThan(0)
  })
})

describe('Workbench / Storage — ST4: loadLayout quarantines wrong schema version', () => {
  it('moves a payload with the wrong version to a corrupt key', () => {
    window.localStorage.setItem(
      KEY,
      JSON.stringify({ version: 999, savedAt: 1, tree: VALID_TREE }),
    )
    const tree = loadLayout(PROJECT, KNOWN)
    expectIsDefaultLayout(tree)
    expect(window.localStorage.getItem(KEY)).toBeNull()
  })
})

describe('Workbench / Storage — ST5: loadLayout quarantines structurally invalid trees', () => {
  it('moves a tree that fails validateTree to a corrupt key', () => {
    // Tabs node with no tabs is structurally invalid.
    window.localStorage.setItem(
      KEY,
      JSON.stringify({
        version: LAYOUT_SCHEMA_VERSION,
        savedAt: 1,
        tree: { kind: 'tabs', id: 'g', tabs: [], activeTabId: 'missing' },
      }),
    )
    const tree = loadLayout(PROJECT, KNOWN)
    expectIsDefaultLayout(tree)
    expect(window.localStorage.getItem(KEY)).toBeNull()
  })
})

describe('Workbench / Storage — ST6: saveLayout writes a versioned payload', () => {
  it('writes a payload with version, savedAt, and the tree', () => {
    saveLayout(PROJECT, VALID_TREE)
    const raw = window.localStorage.getItem(KEY)
    expect(raw).not.toBeNull()
    const parsed = JSON.parse(raw!)
    expect(parsed.version).toBe(LAYOUT_SCHEMA_VERSION)
    expect(parsed.tree).toEqual(VALID_TREE)
    expect(typeof parsed.savedAt).toBe('number')
    expect(parsed.savedAt).toBeGreaterThan(0)
  })
})

describe('Workbench / Storage — ST7: saveLayout swallows storage write errors', () => {
  it('does not throw when localStorage.setItem throws', () => {
    const orig = Storage.prototype.setItem
    Storage.prototype.setItem = vi.fn(() => {
      throw new Error('quota exceeded')
    })
    try {
      // Must not throw — the workbench keeps running in-memory and
      // simply loses cross-reload persistence for this write.
      expect(() => saveLayout(PROJECT, VALID_TREE)).not.toThrow()
    } finally {
      Storage.prototype.setItem = orig
    }
  })
})

describe('Workbench / Storage — ST8/ST9/ST10: makeDebouncedSaver', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('ST8: coalesces multiple save() calls into one write after the delay', () => {
    const saver = makeDebouncedSaver(100)
    saver.save(PROJECT, VALID_TREE)
    saver.save(PROJECT, VALID_TREE)
    saver.save(PROJECT, VALID_TREE)
    expect(window.localStorage.getItem(KEY)).toBeNull()
    vi.advanceTimersByTime(99)
    expect(window.localStorage.getItem(KEY)).toBeNull()
    vi.advanceTimersByTime(2)
    expect(window.localStorage.getItem(KEY)).not.toBeNull()
  })

  it('ST9: flush() writes the pending payload immediately', () => {
    const saver = makeDebouncedSaver(10_000)
    saver.save(PROJECT, VALID_TREE)
    saver.flush()
    expect(window.localStorage.getItem(KEY)).not.toBeNull()
  })

  it('ST10: cancel() drops the pending payload (no write happens)', () => {
    const saver = makeDebouncedSaver(50)
    saver.save(PROJECT, VALID_TREE)
    saver.cancel()
    vi.advanceTimersByTime(1000)
    expect(window.localStorage.getItem(KEY)).toBeNull()
  })

  it('ST10+: switching projectId flushes the prior pending immediately (cross-project safety)', () => {
    // Bug: 単一 singleton の pending を別 projectId の save が上書きすると
    // 前 project の最終 layout が永遠に書かれない。fix: 既存 pending と異なる
    // projectId で save が呼ばれたら即時 flush する。
    const saver = makeDebouncedSaver(100)
    const OTHER = 'proj-OTHER'
    const OTHER_KEY = `workbench:layout:${OTHER}`
    const OTHER_TREE: LayoutTree = { ...VALID_TREE, id: 'other-group' } as LayoutTree
    saver.save(PROJECT, VALID_TREE)
    // この時点では PROJECT の pending のみ。まだ flush されない。
    expect(window.localStorage.getItem(KEY)).toBeNull()
    expect(window.localStorage.getItem(OTHER_KEY)).toBeNull()

    // 異なる projectId の save が来た瞬間、PROJECT の pending が即時書かれる
    saver.save(OTHER, OTHER_TREE)
    expect(window.localStorage.getItem(KEY)).not.toBeNull()
    // OTHER は新しい pending としてデバウンス中
    expect(window.localStorage.getItem(OTHER_KEY)).toBeNull()
    vi.advanceTimersByTime(101)
    expect(window.localStorage.getItem(OTHER_KEY)).not.toBeNull()
  })
})

describe('Workbench / Storage — ST11/ST12: subscribeCrossTab (Phase 6.1 listener-only)', () => {
  beforeEach(() => {
    __resetCrossTabSnapshotsForTesting()
  })

  it('ST11: notifies listener and populates snapshot when another tab writes the same project key', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeCrossTab(PROJECT, KNOWN, listener)
    const newPayload = {
      version: LAYOUT_SCHEMA_VERSION,
      savedAt: 12345,
      tree: VALID_TREE,
    }
    // Synthesize a storage event as if another tab wrote the key.
    const ev = new StorageEvent('storage', {
      key: KEY,
      newValue: JSON.stringify(newPayload),
      storageArea: window.localStorage,
    })
    window.dispatchEvent(ev)
    expect(listener).toHaveBeenCalledTimes(1)
    const snap = getCrossTabSnapshot(PROJECT)
    expect(snap).not.toBeNull()
    expect(snap!.savedAt).toBe(12345)
    expect(snap!.tree).toEqual(VALID_TREE)
    unsubscribe()
  })

  it('ST11.1: getCrossTabSnapshot returns null before any storage event (initial mount)', () => {
    expect(getCrossTabSnapshot(PROJECT)).toBeNull()
  })

  it('ST11.2: a second storage event yields a new snapshot reference (so consumers re-dispatch)', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeCrossTab(PROJECT, KNOWN, listener)
    const fire = (savedAt: number) => {
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: KEY,
          newValue: JSON.stringify({
            version: LAYOUT_SCHEMA_VERSION,
            savedAt,
            tree: VALID_TREE,
          }),
        }),
      )
    }
    fire(1)
    const first = getCrossTabSnapshot(PROJECT)
    fire(2)
    const second = getCrossTabSnapshot(PROJECT)
    expect(listener).toHaveBeenCalledTimes(2)
    expect(first).not.toBe(second)
    expect(second!.savedAt).toBe(2)
    unsubscribe()
  })

  it('ST12: ignores storage events for a different project key', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeCrossTab(PROJECT, KNOWN, listener)
    const ev = new StorageEvent('storage', {
      key: 'workbench:layout:OTHER',
      newValue: JSON.stringify({
        version: LAYOUT_SCHEMA_VERSION,
        savedAt: 1,
        tree: VALID_TREE,
      }),
    })
    window.dispatchEvent(ev)
    expect(listener).not.toHaveBeenCalled()
    expect(getCrossTabSnapshot(PROJECT)).toBeNull()
    unsubscribe()
  })

  it('ST11+: the unsubscribe function detaches the listener and the storage handler', () => {
    const listener = vi.fn()
    const unsubscribe = subscribeCrossTab(PROJECT, KNOWN, listener)
    unsubscribe()
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: KEY,
        newValue: JSON.stringify({
          version: LAYOUT_SCHEMA_VERSION,
          savedAt: 1,
          tree: VALID_TREE,
        }),
      }),
    )
    expect(listener).not.toHaveBeenCalled()
    expect(getCrossTabSnapshot(PROJECT)).toBeNull()
  })
})
