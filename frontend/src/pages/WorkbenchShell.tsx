/**
 * WorkbenchShell — `/projects/:projectId/*` の永続的な親レイアウト。
 *
 * Phase 1 (Lifecycle & Ownership 仕様書 §3.1) で導入。
 *
 * ## 責務
 * 1. `<WorkbenchPage />` を **常に mount したまま** 描画する。
 * 2. 子ルート (`settings`, `documents/:documentId` 等) が match した
 *    場合、その element を overlay として WorkbenchPage の上に被せる。
 * 3. WorkbenchPage は overlay 表示中も DOM ツリーから外さず
 *    `display:none` で隠すだけにすることで、配下の long-lived 接続
 *    (TerminalView の WebSocket、xterm Terminal インスタンス等) を
 *    維持する。
 *
 * ## 不変条件 (Lifecycle & Ownership 仕様書)
 * - **L1 (Phase 1)**: WorkbenchShell は project スコープ内のルート
 *   遷移で unmount しない。projectId が変わるときだけ React Router の
 *   route element 変更で remount される (この segment は Phase 2 で
 *   TerminalHost により解消予定)。
 * - WorkbenchShell の子は **WorkbenchPage 1 個 + 任意の overlay 1 個**
 *   のみ。複数 overlay を同時に積まない。
 *
 * ## 旧設計との差分
 * 旧設計: `/projects/:projectId/settings` は flat な Route だったため
 * settings に遷移すると WorkbenchPage 全体が unmount → TerminalView
 * cleanup → ws.close()。
 *
 * 新設計: settings は WorkbenchShell の子 route。WorkbenchPage は
 * 親が描画し続けるので unmount しない → TerminalView の WS 維持。
 *
 * ## なぜ Outlet を使わず useOutlet?
 * `<Outlet />` を直接置くと「子 route が無いとき何も描画しない」と
 * いう挙動になる。WorkbenchPage を常時描画しつつ overlay を条件付き
 * 描画したいので、`useOutlet()` で element を取得して条件分岐する
 * パターンを採用。
 */
import { useOutlet, useParams } from 'react-router-dom'
import WorkbenchPage from './WorkbenchPage'

export default function WorkbenchShell() {
  const { projectId } = useParams<{ projectId: string }>()
  const overlay = useOutlet()

  if (!projectId) {
    return <div className="p-8 text-gray-400">Invalid project id.</div>
  }

  return (
    <div className="relative h-full w-full">
      {/* WorkbenchPage は常に mount され続ける。overlay 表示中は
          display:none で視覚的に隠すだけ — 配下の WebSocket / xterm
          がそのまま生存する。display:none は再描画コストが極小で、
          xterm.js の WebGL renderer も visibility-aware なので問題
          なく休止する。 */}
      <div
        className="absolute inset-0"
        style={overlay ? { display: 'none' } : undefined}
        aria-hidden={overlay ? true : undefined}
      >
        <WorkbenchPage />
      </div>
      {overlay && (
        <div className="absolute inset-0 bg-gray-900">{overlay}</div>
      )}
    </div>
  )
}
