# Workbench (project workspace)

The Workbench is the per-project workspace at `/projects/:projectId`.
It composes tasks, documents, an error tracker, a remote terminal,
and the project file browser into a custom split-pane layout that
persists across reloads (per-browser, per-project) and is
shareable via URL.

> Phase C2 (2026-04) integration: the Workbench replaced the legacy
> single-page ProjectPage. The previous standalone `/workbench/:id`
> URL no longer exists.

Reach it from the project name in the left sidebar (or any URL of
the form `/projects/:projectId`).

## Pane types

| Type | What it shows | Per-pane state |
|------|---------------|----------------|
| **Tasks** | Board / List / Timeline view of project tasks. Filter / select / archive / column picker / V key to cycle views | `viewMode` |
| **Task Detail** | Single task — same UI as the slide-over but flush in the pane | `taskId` |
| **Documents** | Document list + detail (CRUD, sort, import/export, version history) | `docId` |
| **Doc** | Single document, markdown-rendered (read-only here; full editor lives at `/projects/:id/documents/:did`) | `docId` |
| **Terminal** | Live PTY on the project's bound remote agent | `sessionId`, `agentId` (re-attached on reload) |
| **Files** | Workspace directory listing | `cwd` |
| **Errors** | Error tracker (issues, events, breadcrumbs) | (selection is local to the pane instance) |

Each pane has its own state, so two **Tasks** tabs can show
different view modes, two **Doc** tabs can show different documents,
etc.

## Layout model

The layout is a binary tree of **splits** (horizontal or vertical)
whose leaves are **tab groups**. Each tab group holds 1–8 tabs. The
top of the tree is either a single tab group or a split.

Hard caps:

- Up to **4** tab groups in the entire layout.
- Up to **8** tabs per group.

Splits are resizable by dragging the divider between two children.
Resizes are persisted automatically.

### Pane width breakpoints

A narrow pane can't show some views usefully. The Workbench
automatically degrades:

| Pane width | Effect |
|---|---|
| ≥ 640 px | Full pane mode (Board / Timeline available) |
| 480–640 px | Tasks pane forces **list view** (the user's chosen Board/Timeline is preserved; widening restores it) |
| < 480 px (mobile) | Not officially supported — the Workbench targets desktop |

The 640 px breakpoint catches the common 13" laptop "two panes
side-by-side" case (each pane ≈ 640 px) before Board becomes
unusable.

## Drag and drop (VS Code-style)

Drag any tab header. While dragging, every tab group shows a
5-region overlay:

```
┌───────────────────────────────┐
│             TOP               │
│ ┌─────────────────────────────┤
│ │                              │
│ L           CENTER          R │
│ │                              │
│ ├─────────────────────────────┤
│             BOTTOM             │
└───────────────────────────────┘
```

- **Edge** drops (top/right/bottom/left) split the target group on
  that side. The 4-group cap applies — when full, edges render
  dimmed.
- **Center** drop tabifies into the target group. The insertion
  position is determined by the pointer's X coordinate against
  existing tab rects (a vertical blue line indicates where the tab
  will land). Same-group center drop reorders.
- **ESC** during drag cancels.
- Drops outside the Workbench cancel.

> Keyboard-only DnD is not implemented. The Workbench is a
> personal-use tool (no public release). If we open it up later, we
> revisit WCAG 2.1.1 (Keyboard).

## Cross-pane events

Some panes can drive others by clicking. Routing picks the focused
pane of the right type, then falls back to most-recently-focused,
then the first matching pane. If no pane of the right type exists,
some events open a slide-over fallback.

| Trigger | Event | Routed to | Fallback |
|---|---|---|---|
| Tasks pane: task click | `open-task` | Task Detail pane | Slide-over (legacy modal) |
| Documents pane: document click | `open-doc` | Doc pane | (none — internal detail panel keeps showing it) |
| Files pane: directory Cmd/Ctrl+click | `open-terminal-cwd` | Terminal pane (`cd "<path>"`) | Toast |

The slide-over fallback for `open-task` is provided so a one-pane
layout still gives task detail access — the user doesn't have to
add a Task Detail pane just to view a task.

## URL state contract

The Workbench URL is shareable. Include any of these query
parameters and the matching pane state is set on mount:

| Query | Meaning | Round-trip |
|---|---|---|
| `?task=<taskId>` | Show task in Task Detail pane (or slide-over if no pane) | Yes — clicking a task in Tasks pane updates `?task=` (replace, no history bloat) |
| `?doc=<docId>` | Show doc in Doc pane | Yes — DocPane selection writes `?doc=` |
| `?view=board\|list\|timeline` | Override the Tasks pane viewMode | Yes — viewMode change writes `?view=` (board is implicit and omitted from URL) |
| `?layout=<presetId>` | Apply a preset layout (one-shot, not persisted) | No — used for sharing a configuration |
| `?group=<groupBy>` | Timeline groupBy hint (parsed but not yet wired to TaskTimeline) | No |

Unknown query values fall back to defaults and emit a
`console.warn` for development. The URL is never the cause of a
white screen.

The header **Copy URL** button copies the current URL to your
clipboard so a snapshot of the layout + selected items can be
shared (or bookmarked).

### Legacy URL compatibility

Old `?view=docs` / `?view=files` / `?view=errors` URLs (used by the
ProjectPage that the Workbench replaced) automatically add the
matching pane and surface an info toast. The toast layer is set to
sunset 6 months after Phase C2 ships.

### Header back link

The header back arrow always navigates to `/projects` (the
project list), not `navigate(-1)`. Deep-link arrival in a fresh
tab has an empty history stack, so a fixed target is the only
reliable "go back" affordance.

## Layout presets

The header's **Layout** menu offers five starting points:

1. **Tasks only** — single tab group with a Tasks pane (the default
   on first visit, also used by the Reset button).
2. **Tasks + Detail** — Tasks list on the left, Task Detail on the
   right. The most common pattern for triaging tasks.
3. **Tasks + Terminal** — Tasks above, Terminal below.
4. **Tasks + Doc + Terminal** — Tasks on the left; Doc above
   Terminal on the right.
5. **Doc + Files** — Doc on the left, file browser on the right.

Loading a preset replaces the current layout (a confirmation modal
prevents accidents). Per-pane *server* data is unaffected.

## Keyboard shortcuts

| Shortcut | Action |
|----------|--------|
| `Cmd/Ctrl + W` | Close the focused pane |
| `Cmd/Ctrl + \` | Split the focused pane vertically (new pane = same type) |
| `Cmd/Ctrl + Shift + \` | Split horizontally |
| `Cmd/Ctrl + 1..4` | Focus the Nth pane (DFS / reading order) |
| `Cmd/Ctrl + Shift + R` | Reset layout (with confirmation) |
| `V` (Tasks pane focused) | Cycle Board → List → Timeline |
| `ESC` (during drag) | Cancel drag |

## Persistence

The layout is stored in `localStorage` under
`workbench:layout:v1:{projectId}` (schema versioned via the `v1`
segment). The shape is:

```json
{
  "version": 1,
  "savedAt": 1714000000000,
  "tree": { "id": "...", "kind": "tabs", "tabs": [...], "activeTabId": "..." }
}
```

- **Cross-tab sync**: opening the same project in two browser tabs
  syncs layouts via `storage` events; last-write-wins.
- **Schema versioning**: a future-incompatible bump replaces the
  stored layout with the default. Corrupted JSON is moved to
  `:corrupt-{ts}` so the user can inspect it.
- **Reset**: the **Reset** button in the header (or
  `Cmd+Shift+R`) replaces the layout with the default. To wipe all
  per-project state from the browser, clear keys that match the
  prefix above in DevTools.

## Extending

Add a pane type by:

1. Adding the literal to `PaneType` in
   `frontend/src/workbench/types.ts`.
2. Writing a component that satisfies `PaneComponentProps` (in
   `frontend/src/workbench/paneRegistry.tsx`).
3. Registering the component in the same file, plus a label and an
   entry in `SELECTABLE_TYPES` (`frontend/src/workbench/TabGroup.tsx`).

The Workbench picks up the new type automatically; old layouts that
don't reference it are unaffected. Layouts that *do* reference an
unknown type render the `unsupported` placeholder pane so the
overall structure survives downgrades.

When you want a new cross-pane interaction:

1. Add the event to `WorkbenchEventMap` in
   `frontend/src/workbench/eventBus.tsx`, plus its target pane type
   in `EVENT_TARGET_TYPE` and a fallback message.
2. The emitter calls `bus.emit('your-event', payload)`.
3. The receiver subscribes via `useWorkbenchEvent(paneId, 'your-event', cb)`.
4. If the event needs a slide-over fallback, register
   `bus.setFallback('your-event', cb)` from `WorkbenchPage`
   (`WorkbenchFallbacks` is a good home).
