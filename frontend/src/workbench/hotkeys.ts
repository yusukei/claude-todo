/**
 * Keyboard shortcuts for the Workbench. Bound at the page level so
 * the handlers see the latest tree + dispatcher refs without going
 * through prop drilling.
 *
 * Resolving "the focused pane" is done from ``document.activeElement``
 * by walking up to the nearest ancestor that carries
 * ``data-pane-id`` — the attribute is set by ``PaneFrame``. This
 * keeps focus tracking in one place and naturally handles cases
 * where the pane content (a button, a markdown link, a terminal)
 * holds the actual DOM focus.
 */
import type { LayoutTree, Pane } from './types'

/** Walk every leaf pane in DFS order. The order matches the visual
 *  reading order on screen (left-to-right for horizontal splits,
 *  top-to-bottom for vertical splits) because that's how the
 *  recursive renderer traverses children. */
export function dfsPanes(tree: LayoutTree): Pane[] {
  if (tree.kind === 'tabs') return [...tree.tabs]
  return tree.children.flatMap(dfsPanes)
}

/** Find the group containing a pane id. Returns ``null`` when the
 *  id isn't in the tree. */
export function findGroupIdOf(
  tree: LayoutTree,
  paneId: string,
): string | null {
  if (tree.kind === 'tabs') {
    return tree.tabs.some((p) => p.id === paneId) ? tree.id : null
  }
  for (const c of tree.children) {
    const r = findGroupIdOf(c, paneId)
    if (r) return r
  }
  return null
}

/** Resolve "the currently focused pane" by walking up from
 *  ``document.activeElement`` to the nearest ancestor with
 *  ``data-pane-id``. Returns ``null`` if focus is outside the
 *  Workbench. */
export function resolveFocusedPaneId(): string | null {
  if (typeof document === 'undefined') return null
  let el: Element | null = document.activeElement
  while (el && el !== document.body) {
    const id = (el as HTMLElement).dataset?.paneId
    if (id) return id
    el = el.parentElement
  }
  return null
}

/** Move keyboard focus to a pane's frame so subsequent shortcuts
 *  resolve back to the same pane. Caller is responsible for first
 *  switching the active tab if the pane lives in a hidden tab. */
export function focusPaneFrame(paneId: string): void {
  if (typeof document === 'undefined') return
  const el = document.querySelector<HTMLElement>(
    `[data-pane-id="${paneId}"]`,
  )
  el?.focus()
}

// ── Hotkey detection ──────────────────────────────────────────

export type HotkeyName =
  | 'close-pane'
  | 'split-vertical'
  | 'split-horizontal'
  | 'reset-layout'
  | 'focus-1'
  | 'focus-2'
  | 'focus-3'
  | 'focus-4'

/** Map a ``KeyboardEvent`` to the corresponding Workbench hotkey, or
 *  ``null`` if it doesn't match. Pulled out as a pure function for
 *  testability — the binding effect just dispatches based on the
 *  return value. */
export function matchHotkey(e: KeyboardEvent): HotkeyName | null {
  // Cmd on macOS, Ctrl elsewhere. We accept either to keep the
  // shortcut working when the user is on a non-mac browser even on
  // a mac (e.g. inside a remote-desktop session).
  const mod = e.metaKey || e.ctrlKey
  if (!mod) return null
  // Avoid stepping on input fields (tab body's textareas / xterm
  // canvas etc) for shortcuts that would otherwise be common
  // browser bindings (Cmd+W). Cmd+W in a textbox is unusual but the
  // user intent is "close the pane I'm working in", so we let it
  // through; the focused pane is resolved by data-pane-id which
  // includes the textbox's pane.
  switch (e.key.toLowerCase()) {
    case 'w':
      // Cmd+W in a browser closes the tab — we steal it because the
      // user is in the Workbench *web app* and almost never wants
      // the browser-tab close while a pane has focus. Caller should
      // call preventDefault on a non-null match to actually steal.
      return e.shiftKey ? null : 'close-pane'
    case '\\':
      return e.shiftKey ? 'split-horizontal' : 'split-vertical'
    case 'r':
      return e.shiftKey ? 'reset-layout' : null
    case '1':
      return 'focus-1'
    case '2':
      return 'focus-2'
    case '3':
      return 'focus-3'
    case '4':
      return 'focus-4'
    default:
      return null
  }
}

/** Map a focus hotkey name to the 1-based pane index. */
export function focusIndex(h: HotkeyName): number | null {
  if (!h.startsWith('focus-')) return null
  return parseInt(h.slice('focus-'.length), 10)
}
