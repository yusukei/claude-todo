/**
 * Centralised React Query key factory.
 *
 * Phase B / 修正計画 §3 Phase 4 に従う. 散在していた inline キー
 * (`['tasks', projectId]` 等) を type-safe な factory に集約.
 *
 * ## 設計方針
 *
 * **既存 inline キーの shape を保つ** ため、factory が返すキーは
 * 既存コードと bit 互換. これにより consumer 側を順次 migrate しても
 * useSSE 側の invalidation が破綻しない (両者は同じキー shape を
 * 共有). 例: `qk.task(id) === ['task', id]`.
 *
 * 階層化 (mcp-todo prefix を被せる) するとさらに prefix-based
 * invalidation が便利になるが、**段階移行を優先** して shape は維持.
 * Phase 4.5 (将来) で root prefix を導入する余地を残す.
 *
 * ## 使い方
 *
 * ```ts
 * useQuery({ queryKey: qk.task(taskId), queryFn: ... })
 * qc.invalidateQueries({ queryKey: qk.tasksInProject(projectId) })
 * ```
 */

export const qk = {
  // ── Tasks ───────────────────────────────────────────────────
  /** 全プロジェクトのタスク (cross-project Live Activity 等). */
  tasksAll: () => ['tasks'] as const,
  /** Live Activity panel 用 (`['tasks', 'live']`). */
  tasksLive: () => ['tasks', 'live'] as const,
  /** Project 単位のタスク list. projectId が undefined の場合は
   *  prefix-only invalidate (= ['tasks']) として動作する. */
  tasksInProject: (projectId: string | undefined) =>
    ['tasks', projectId] as const,
  /** 単一タスク詳細. id が unknown 型でもそのまま渡せる. */
  task: (taskId: string | undefined | unknown) =>
    ['task', taskId] as const,
  /** タスクサマリ (project 配下). */
  projectSummary: (projectId: string | undefined) =>
    ['project-summary', projectId] as const,
  /** 今日の活動 stats (sidebar). projectId 省略時は global stats. */
  statsToday: (projectId?: string) =>
    projectId ? (['stats:today', projectId] as const) : (['stats:today'] as const),

  // ── Projects ────────────────────────────────────────────────
  /** Project 一覧. */
  projects: () => ['projects'] as const,
  /** 単一 project. */
  project: (projectId: string) => ['project', projectId] as const,
  /** 管理画面の全 project 一覧 (admin scope). */
  adminProjects: () => ['admin-projects'] as const,

  // ── Workbench layout ────────────────────────────────────────
  workbenchLayout: (projectId: string) =>
    ['workbench-layout', projectId] as const,

  // ── Documents ───────────────────────────────────────────────
  documents: (projectId: string, folderPath?: string) =>
    folderPath
      ? (['documents', projectId, folderPath] as const)
      : (['documents', projectId] as const),
  /** workbench-picker 用の docs list (DocPane 内部). */
  documentsPicker: (projectId: string) =>
    ['documents', projectId, 'workbench-picker'] as const,
  document: (projectId: string, documentId: string) =>
    ['document', projectId, documentId] as const,
  /** Obsidian Phase 1 F1 用 folder ツリー. */
  folders: (projectId: string) => ['folders', projectId] as const,

  // ── Bookmarks ───────────────────────────────────────────────
  bookmarks: (projectId: string) => ['bookmarks', projectId] as const,
  bookmarkCollections: (projectId: string) =>
    ['bookmark-collections', projectId] as const,

  // ── Knowledge ───────────────────────────────────────────────
  knowledge: () => ['knowledge'] as const,
  knowledgeItem: (id: string) => ['knowledge', id] as const,

  // ── Workspace / Agents / Terminal ───────────────────────────
  workspaceAgents: () => ['workspace-agents'] as const,
  workspaceAgent: (agentId: string | null) =>
    ['workspace-agent', agentId] as const,
  terminalSessions: (agentId: string) =>
    ['terminal-sessions', agentId] as const,

  // ── Auth / Users ────────────────────────────────────────────
  authMe: () => ['auth', 'me'] as const,
  users: () => ['users'] as const,
  user: (userId: string) => ['user', userId] as const,
} as const
