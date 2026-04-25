# Workbench

The Workbench is a per-project split-pane workspace at
`/workbench/{projectId}`. It lets you compose tasks, documents, a
remote terminal, and the project file browser into a custom layout
that persists across reloads (per-browser, per-project).

Reach it from the project row in the left sidebar (the dashboard
icon next to the cog) or by typing the URL directly.

## Pane types

| Type | What it shows | Per-pane state |
|------|---------------|----------------|
| **Tasks** | The project's tasks list (compact view) | `viewMode` (list / board / timeline; only list is implemented for now) |
| **Doc** | A single project document with markdown rendering | `docId` |
| **Terminal** | A live PTY on the project's bound remote agent | `sessionId`, `agentId` (re-attached on reload) |
| **Files** | The project's workspace directory listing | `cwd` |

Each pane has its own state, so two `Tasks` tabs can show different
view modes, two `Doc` tabs can show different documents, etc.

## Layout model

The layout is a binary tree of **splits** (horizontal or vertical)
whose leaves are **tab groups**. Each tab group holds 1–8 tabs. The
top of the tree is either a single tab group or a split.

Hard caps:

- Up to **4** tab groups in the entire layout.
- Up to **8** tabs per group.

Splits are resizable by dragging the divider between two children.
Resizes are persisted automatically.

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

## Cross-pane events

Some panes can drive others by clicking. Routing picks the focused
pane of the right type, then falls back to most-recently-focused,
then the first matching pane.

- **Files: directory Cmd/Ctrl+click** → `cd "<path>"` runs in the
  active Terminal pane.
- **Files: markdown click** currently surfaces a notice — workspace
  files aren't yet linked to project Docs (see follow-up task in
  Phase C).

## Layout presets

The header's **Layout** menu offers four starting points:

1. **Tasks only** — single tab group with a Tasks pane. Same as the
   default and the Reset button.
2. **Tasks + Terminal** — Tasks above, Terminal below.
3. **Tasks + Doc + Terminal** — Tasks on the left; Doc above
   Terminal on the right.
4. **Doc + Files** — Doc on the left, file browser on the right.

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
| `ESC` (during drag) | Cancel drag |

The shortcuts intentionally steal `Cmd+W` from the browser tab —
inside the Workbench app that's almost always the desired meaning.

## Persistence

The layout is stored in `localStorage` under
`workbench:layout:v1:{projectId}`. The shape is:

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
3. Registering the component in the same file, plus a label.

The Workbench picks up the new type automatically; old layouts that
don't reference it are unaffected. Layouts that *do* reference an
unknown type render the `unsupported` placeholder pane so the
overall structure survives downgrades.
