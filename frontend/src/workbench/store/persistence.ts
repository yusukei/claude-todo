/**
 * Workbench 永続化の dispatcher 側ヘルパ.
 *
 * # 設計 (2026-04-27 redesign)
 *
 * - **localStorage は同期書き込み** (debounce 廃止). user action 時点で
 *   即座に確定し、project 切替で前 project の最新 layout が消える
 *   タイミングの穴を構造的に取り除く。JSON.stringify + setItem は数百μs
 *   程度で、user action は離散イベント (split / closeTab / addTab 等) なので
 *   オーバーヘッドは無視できる。
 *
 * - **server saver は projectId 単位の独立 queue**. ``Map<projectId, slot>``
 *   で各 project の pending + timer を分離。前 project の pending が新
 *   project の save() で上書きされない。
 *
 * - **project 切替時は前 project の pending PUT を即時 flush** —
 *   ``flushServerForProject`` を ``useWorkbenchStore`` の unmount cleanup で
 *   呼ぶことで、A→B 切替時に A の最終 layout が確実に server へ届く。
 *
 * これにより A→B→A→B→A のような複数ラウンドの project 切替でも
 * 各 project の layout が独立に保持される。
 */
import {
  beaconLayout,
  makeServerSaver,
} from '../../api/workbenchLayouts'
import {
  getOrCreateClientId,
  saveLayout,
} from '../storage'
import { LAYOUT_SCHEMA_VERSION } from '../types'
import type { LayoutTree } from '../types'

const serverSaver = makeServerSaver(500, () => getOrCreateClientId())

/** localStorage に同期書き込み. user action 時に呼ばれ、debounce 無し。
 *  PersistedLayout.savedAt に Date.now() が入るので initializeWorkbench
 *  が ``state.lastUserActionAt`` の初期値として復元できる. */
export function saveLocal(projectId: string, tree: LayoutTree): void {
  saveLayout(projectId, tree)
}

/** debounce 付き server PUT (500ms, projectId 単位の独立 queue). */
export function saveServerDebounced(
  projectId: string,
  tree: LayoutTree,
): void {
  serverSaver.save(projectId, tree)
}

/** 指定 projectId の pending server PUT を即時 fire.
 *  project 切替時の unmount cleanup から呼ぶ. */
export function flushServerForProject(projectId: string): void {
  serverSaver.flush(projectId)
}

/** すべての projectId の pending を fire. visibilitychange='hidden' で使う. */
export function flushPersistence(): void {
  serverSaver.flushAll()
}

/** すべての保留中 server PUT を破棄. ロールバック用. */
export function cancelPersistence(): void {
  serverSaver.cancelAll()
}

/** beforeunload / pagehide で navigator.sendBeacon に最終 layout を流す.
 *  当該 projectId の pending PUT は cancel する (beacon が代替するので
 *  二重送信を避ける). */
export function flushBeacon(projectId: string, tree: LayoutTree): void {
  serverSaver.cancel(projectId)
  beaconLayout(projectId, {
    tree,
    schema_version: LAYOUT_SCHEMA_VERSION,
    client_id: getOrCreateClientId(),
  })
}
