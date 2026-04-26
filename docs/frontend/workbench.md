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

The layout has **two stores** that work together:

1. **`localStorage` cache** keyed by `workbench:layout:{projectId}`
   — fast-path for first paint, also acts as offline fallback.
2. **Server-side store** keyed by `(user_id, project_id)` —
   authoritative across devices and reloads (Phase B,
   `/api/v1/workbench/layouts/{project_id}`).

The wire shape stored in localStorage is:

```json
{
  "version": 1,
  "savedAt": 1714000000000,
  "tree": { "id": "...", "kind": "tabs", "tabs": [...], "activeTabId": "..." }
}
```

The server returns `{tree, schema_version, client_id, updated_at}`
where `client_id` is the writing tab's identifier (used by that tab
to skip its own SSE echo).

- **First paint**: hydrate from `localStorage` immediately, then
  fetch from server in the background and replace state if the
  server version is newer / different.
- **Save**: every layout mutation writes localStorage immediately
  and PUTs to the server with a 500 ms debounce. Debounced PUT is
  flushed via `navigator.sendBeacon` on `visibilitychange (hidden)`
  / `pagehide` so a fast reload never loses the last edit.
- **Cross-device / cross-browser sync**: the server publishes a
  `workbench.layout.updated` SSE event scoped to the writing user
  on every successful PUT. Other tabs invalidate the layout query
  and re-hydrate; the writing tab skips the echo by comparing
  `client_id`.
- **Cross-tab sync (same browser)**: still mediated through
  `storage` events as a redundant pathway when the SSE round trip
  is slow.
- **Schema versioning**: a future-incompatible bump replaces the
  stored layout with the default. Corrupted JSON is moved to
  `:corrupt-{ts}` so the user can inspect it.
- **Project switch**: when the route's `:projectId` changes, the
  Workbench hydrates from the *new* project's localStorage + server
  data. **A pending debounced save for the previous project must
  not be flushed against the new project's slot.**
- **Reset**: the **Reset** button in the header (or
  `Cmd+Shift+R`) replaces the layout with the default.

### Per-tab client identifier

Each browser tab generates a UUID on first use and stores it under
`workbench:clientId` in **`sessionStorage`** (per-tab, survives
reload). The id is sent on every PUT and the server echoes it in
the SSE `workbench.layout.updated` payload so the originating tab
can skip its own change.

## Reattach behavior (terminal pane)

When a Terminal pane reattaches to an existing PTY (after a reload
or tab re-mount), it replays the agent-side scrollback so the
visible state matches what the user saw before the disconnect.
Constraints:

- **No status banner** is written after replay (no
  `[reattached]` / `[reattached to an exited session — read-only]`
  line). Extra writeln'd output shifts the prompt and breaks TUI
  layouts whose cursor positions were captured in the scrollback
  (vim, less, fzf, etc.). Connection state is surfaced via the
  pane header instead.
- **Scrollback is written in a single batched call** so xterm's
  renderer flushes once instead of once-per-chunk. Per-chunk
  flushes were the source of visible flicker on slow reconnects.
- **DA / DSR / cursor-position queries embedded in the scrollback
  must NOT leak back to the PTY as input.** xterm's ANSI parser
  auto-replies to those queries via the same `onData` callback
  that carries live keystrokes. The replay path gates `onData`
  for the duration so the response (e.g. `\x1b[?1;2c`) is dropped
  rather than echoed at the prompt.

## Pane lifecycle (mount / keep-alive)

The active tab in each tab group is mounted normally. Inactive tabs
are unmounted **except** for pane types whose `keepAlive` flag is
set in the registry — those stay mounted with `display: none` so
their long-lived connections (WebSocket, PTY, SSE subscription)
survive a tab switch.

Currently `keepAlive` types: `terminal`. Other types are unmounted
and re-mount on next activation; their data refetches via the
shared React Query cache.

## Invariants

The behaviors above are encoded as testable invariants. Tests
reference these IDs in their `describe`/`it` titles. **Failing
tests are spec violations — fix the implementation, not the test.**

Each invariant carries an **axis tag** (1–8) referencing the
"Correctly Working" framework in `CLAUDE.md`:

- 1 Specified · 2 Tested · 3 Implemented · 4 Shipped (process)
- 5 Reachable · 6 Operable · 7 Persistent · 8 Recoverable (user)

The tag identifies what kind of breakage the invariant guards
against. **Coverage gaps on axes 5–8 are how broken UIs ship past
green tests** — every feature should have at least one invariant
per relevant user-axis (5/6/7/8) before being called done.

### Persistence (P)

| ID | Axis | Invariant |
|----|---|-----------|
| P1 | 7 | `workbench:clientId` lives in `sessionStorage`; first read on a fresh tab generates a v4-ish UUID, repeat reads in the same tab return the same value. |
| P2 | 8 | `getServerLayout(projectId)` returns `null` on 404. |
| P3 | 6 | `getServerLayout` returns the server JSON on 200. |
| P4 | 6 | `putServerLayout` includes `tree`, `schema_version`, `client_id` in the body. |
| P5 | 6 | `makeServerSaver(delay, getId, onSaved)` debounces multiple `save()` calls into one PUT after `delay` ms; `onSaved` receives the response `updated_at`. |
| P6 | 6 | `makeServerSaver.flush()` PUTs immediately; `cancel()` drops the pending payload. |
| P7 | 7 | `beaconLayout(projectId, body)` calls `navigator.sendBeacon` against `/api/v1/workbench/layouts/{projectId}/beacon` with the JSON body. |
| P8 | 6 | On WorkbenchPage mount, the visible tree comes from `localStorage` before the server fetch resolves. |
| P9 | 7 | When `getServerLayout` resolves with a different `client_id` than `clientIdRef.current`, the tree is replaced. |
| P10 | 7 | When `getServerLayout` resolves with the *same* `client_id`, no replace happens (echo skip). |
| P11 | 7 | When `getServerLayout` resolves with the same `updated_at` as `lastServerStampRef.current`, no replace happens. |
| P12 | 7 | A user-initiated layout mutation triggers `putServerLayout` after the 500 ms debounce. |
| P13 | 7 | `visibilitychange (hidden)` cancels the pending debounce and calls `beaconLayout` with the most recent tree. |
| P14 | 7 | `pagehide` cancels the pending debounce and calls `beaconLayout` with the most recent tree. |
| P15 | 7 | An SSE `workbench.layout.updated` event invalidates the `['workbench-layout', projectId]` React Query. |
| P16 | 7 | Switching `projectId` (route change) **must not** PUT the previous project's tree to the new project's slot. |
| P17 | 7 | Switching `projectId` re-hydrates from the new project's localStorage + server data. |

### Pane lifecycle (L)

| ID | Axis | Invariant |
|----|---|-----------|
| L1 | 6 | The active tab's pane is mounted. |
| L2 | 6 | A non-`keepAlive` inactive tab pane is unmounted. |
| L3 | 7 | A `keepAlive` inactive tab pane (e.g. `terminal`) stays mounted but is hidden via `display: none`. |
| L4 | 7 | Switching active tab back to a previously visible pane does NOT remount it (the same React component instance). |

### Callback stability (C)

| ID | Axis | Invariant |
|----|---|-----------|
| C1 | 6 | `onConfigChange`, `onActivateTab`, `onCloseTab`, `onAddTab`, `onChangePaneType`, `onSplit`, `onCloseGroup`, `onSplitSizes`, `onMoveTab` props passed from `WorkbenchPage` to children retain identity across `state.tree` changes. |
| C2 | 6 | `TerminalPane.handleSessionStarted` retains identity across `state.tree` changes. |

### TabGroup menu (M)

| ID | Axis | Invariant |
|----|---|-----------|
| M1 | 5 | Clicking the MoreVertical button opens the group menu. |
| M2 | 5 | Clicking outside the group menu closes it. |
| M3 | 5 | Pressing ESC closes the group menu. |
| M4 | 5 | Hovering or moving the cursor between the parent menu and the "Change type" submenu does NOT close the menu (no premature `mouseLeave` close). |
| M5 | 5 | Selecting a type in the submenu closes both menus and calls `onChangePaneType(activeTab.id, selectedType)`. |
| M6 | 5 | `SELECTABLE_TYPES` includes `terminal` (so the user can convert a tab to a Terminal pane). |

### TerminalView reattach (T)

| ID | Axis | Invariant |
|----|---|-----------|
| T1 | 7 | When `session_started` arrives with `attached: true`, scrollback chunks are written to xterm. |
| T2 | 6 | Scrollback is batched into a single `terminal.write(combined, callback)` call (no per-chunk write loop). |
| T3 | 6 | While replaying scrollback, `onData` callbacks are dropped (no bytes are sent to the WebSocket as input). |
| T4 | 6 | After replay completes, `onData` callbacks resume normally. |
| T5 | 6 | No `[reattached]` text is written to the terminal. |
| T6 | 6 | No `[reattached to an exited session — read-only]` text is written. |
| T7 | 6 | A fresh session (`attached: false`) does NOT trigger scrollback replay. |

### WorkbenchPage header (H)

| ID | Axis | Invariant |
|----|---|-----------|
| H1 | 5 | Header has a `← projects` link that navigates to `/projects` (fixed target — never `navigate(-1)`). |
| H2 | 6 | Header shows the current project name (from `useQuery(['project', projectId])`). |
| H3 | 5 | Header has a **Layout** menu listing all 5 presets; clicking a preset opens a confirmation modal. |
| H4 | 5 | Header has a **Copy URL** button that calls `navigator.clipboard.writeText(window.location.href)`. |
| H5 | 5 | Header has a **Reset** button that opens the same confirmation modal pre-bound to the `tasks-only` preset. |
| H6 | 5 | The reset / preset confirmation modal closes on ESC and confirms on Enter. |

### TaskDetailPane (TD)

| ID | Axis | Invariant |
|----|---|-----------|
| TD1 | 8 | When `paneConfig.taskId` is absent, the pane shows an empty-state placeholder asking the user to click a task in the Tasks pane. |
| TD2 | 6 | When `open-task` event fires, the pane updates `paneConfig.taskId` (subscribed via `useWorkbenchEvent`). |

### DocumentsPane (DP)

| ID | Axis | Invariant |
|----|---|-----------|
| DP1 | 6 | Selecting a document emits the `open-doc` event with the doc id (so any DocPane in the layout follows). |
| DP2 | 7 | The selected doc id is persisted via `paneConfig.docId`. |

### DocPane (D)

| ID | Axis | Invariant |
|----|---|-----------|
| D1 | 8 | When `paneConfig.docId` is absent, an empty-state with a CTA is shown. |
| D2 | 5 | When a doc is loaded, an **Open in editor** link navigates to `/projects/:id/documents/:did`. |

### FileBrowserPane (FB)

| ID | Axis | Invariant |
|----|---|-----------|
| FB1 | 6 | Cmd/Ctrl + click on a directory entry emits `open-terminal-cwd` with the path. |

### TerminalPane (TM)

| ID | Axis | Invariant |
|----|---|-----------|
| TM1 | 8 | When the project has no remote agent bound (`project.remote == null`), the pane shows an empty-state CTA linking to `/projects/:id/settings`. |
| TM2 | 8 | When the agent is bound but the stored `paneConfig.sessionId` no longer exists on the agent, the pane drops the stale id so the next mount creates a fresh session. |

#### TerminalPane usability gaps (axes 6 / 7 not yet covered)

The invariants above only guard axis 8 (Recoverable). They do **not**
guarantee that the terminal *visibly works* once the agent is bound,
which is what the user reported as "ターミナルが開けない" (axis 6
Operable failure). Until the following invariants are added and
green, the terminal pane is **not** considered "correctly working"
per the CLAUDE.md framework.

| Proposed ID | Axis | Invariant (to be added) |
|---|---|---|
| TM3 | 6 | When `project.remote.agent_id` is bound and `paneConfig.sessionId` is absent, the pane mounts and visibly shows a "Connecting…" state within 1 s of mount. |
| TM4 | 6 | When `session_started` arrives with `attached: false`, an xterm canvas with non-zero dimensions becomes visible. |
| TM5 | 6 | The xterm container fills the pane (non-zero width × height) regardless of whether the pane is wrapped in `absolute inset-0` (TabGroup keep-alive) or normal flex flow. |
| TM6 | 6 | A keystroke fired through `terminal.onData` reaches the WebSocket as `{type:"input", data}`. |
| TM7 | 4 | The deployed bundle's `WorkbenchPage-*.js` and `TerminalView-*.js` chunks contain the latest implementation hash (verified post-deploy, not just post-build). |

### Sidebar (Layout) navigation (S)

| ID | Axis | Invariant |
|----|---|-----------|
| S1 | 5 | The project name in the sidebar is a link to `/projects/:id`. |
| S2 | 5 | The Settings cog icon next to a project navigates to `/projects/:id/settings`. |
| S3 | 5 | The sidebar lists global affordances (projects, bookmarks, knowledge, docsites). |

### TasksPane affordances (TP)

| ID | Axis | Invariant |
|----|---|-----------|
| TP1 | 5 | The toolbar contains a **Create Task** affordance (button) that opens `TaskCreateModal` for the current `projectId`. |
| TP2 | 6 | The Create Task modal closes on the user's request (cancel / X / outside click) and on successful create. |
| TP3 | 5 | The Create Task affordance is hidden when the project is locked (matches legacy ProjectPage's `!project.is_locked` gate). |

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
