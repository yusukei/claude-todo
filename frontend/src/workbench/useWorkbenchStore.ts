/**
 * Workbench reducer + dispatcher を 1 hook にまとめた API.
 *
 * Phase B 設計書 v2.1 §4.4.3 の `useWorkbenchStore` 実装.
 *
 * ## 設計
 *
 * - **lazy initializer** で初期 state を構築 (StrictMode 冪等).
 * - **dispatch** は `action.kind` で副作用を分岐:
 *     - user.* → reducer 後の next.tree を localStorage / server に
 *                debounced save、URL に同期書き戻し.
 *     - remote.* / system.* → 副作用なし (echo loop 構造防止).
 * - **stable identity**: `dispatch` の identity が変わらないよう
 *   `stateRef` / `searchParamsRef` 経由で stale closure を避けつつ
 *   `useCallback([projectId], ...)` で固定する.
 *
 * ## 戻り値
 *
 *   - `state`              最新 reducer state
 *   - `dispatch`           安定 callback (Action を受ける)
 *   - `taskFallbackId`     ?task=<id> hydrate で task-detail pane が
 *                           無かった場合の fallback 用 task id (null
 *                           可). page 側で slide-over 表示.
 *   - `setTaskFallbackId`  fallback の制御用.
 *   - `clearTaskFallback`  ショートカット (= setTaskFallbackId(null)).
 */
import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { Action } from './store/actions'
import { isUserAction } from './store/actions'
import { initializeWorkbench } from './store/initialState'
import {
  flushServerForProject,
  saveLocal,
  saveServerDebounced,
} from './store/persistence'
import { reducer, type State } from './store/reducer'
import { syncUrlFromState } from './store/urlSync'

interface UseWorkbenchStoreReturn {
  state: State
  dispatch: (action: Action) => void
  taskFallbackId: string | null
  clearTaskFallback: () => void
  setTaskFallbackId: (id: string | null) => void
}

/**
 * `WorkbenchPage` の中核 hook.
 *
 * Phase 1 (Lifecycle & Ownership 仕様書 §3.1) 後の挙動:
 *   - projectId は mount 時に固定ではなく、変更を検知して reducer に
 *     `system.resetForProject` を dispatch することで内部 state を新
 *     project の initial value に切り替える。
 *   - 旧設計の `<WorkbenchPageBody key={projectId} />` による強制
 *     remount を排除し、配下の long-lived 接続 (TerminalView の WS 等)
 *     が project-internal なルート遷移で生き残るようにする。
 *
 * project 切替の流れ:
 *   1. WorkbenchShell の useParams から渡される projectId が変化
 *   2. 下記 useEffect が old-project の pending PUT を flush
 *   3. initializeWorkbench(newProjectId) で新 initial state を構築
 *   4. dispatchRaw({ kind: 'system.resetForProject', ... }) で reducer state 更新
 *   5. taskFallbackId も同じタイミングで再計算
 */
export function useWorkbenchStore(projectId: string): UseWorkbenchStoreReturn {
  const [searchParams, setSearchParams] = useSearchParams()

  // 最新参照を ref で保持して dispatch を安定させる
  const searchParamsRef = useRef(searchParams)
  searchParamsRef.current = searchParams
  const setSearchParamsRef = useRef(setSearchParams)
  setSearchParamsRef.current = setSearchParams

  // ── lazy initialize ──────────────────────────────────────
  // useRef 経由で StrictMode 二重評価でも初期化を 1 回に抑える.
  // (useReducer の lazy initializer は state しか返せないので、
  //  taskFallbackId / hadUnknownValue を一緒に取り出すために自前で
  //  initRef にキャッシュする.)
  // initRef.current.projectId で「どの project で初期化したか」を保持
  // し、後続の useEffect で projectId 変更を検知する。
  const initRef = useRef<{
    projectId: string
    state: State
    taskFallbackId: string | null
  } | null>(null)
  if (initRef.current === null) {
    const init = initializeWorkbench({ projectId, searchParams })
    if (init.hadUnknownValue) {
      // eslint-disable-next-line no-console
      console.warn(
        '[Workbench] URL contained unknown query value(s); using defaults',
      )
    }
    initRef.current = {
      projectId,
      state: init.state,
      taskFallbackId: init.taskFallbackId,
    }
  }

  const [reducerState, dispatchRaw] = useReducer(
    reducer,
    initRef.current.state,
  )
  const [taskFallbackId, setTaskFallbackId] = useState<string | null>(
    initRef.current.taskFallbackId,
  )

  // 最新 state を closure stale させずに副作用ハンドラに渡す.
  const stateRef = useRef(reducerState)
  stateRef.current = reducerState

  // 注: dispatch の identity を完全 stable に保つため、最新値は
  //     ref 経由で参照する (古典的 stable callback パターン).
  const dispatch = useCallback(
    (action: Action) => {
      // 1. reducer (純関数) で次の state を計算
      const next = reducer(stateRef.current, action)

      // 2. state を更新
      dispatchRaw(action)

      // 3. action.kind で副作用を分岐 (Phase B 設計 v2.1 §4.4.3)
      if (isUserAction(action)) {
        // tree が変わっていない (no-op mutator) ときは save しない
        if (next.tree === stateRef.current.tree) return
        // localStorage は同期書き込み (debounce 廃止). user action 時点で
        // 確実に永続化することで、project 切替の race を構造的に排除する.
        saveLocal(projectId, next.tree)
        saveServerDebounced(projectId, next.tree)
        syncUrlFromState(
          next,
          searchParamsRef.current,
          setSearchParamsRef.current,
        )
      }
    },
    [projectId],
  )

  const clearTaskFallback = useCallback(() => setTaskFallbackId(null), [])

  // ── Project 切替検知 + Unmount flush ──────────────────────
  // Phase 1: 旧設計では親が `key={projectId}` で remount し、unmount
  // cleanup で前 project の pending PUT を flush していた。Phase 1 では
  // remount しないので、projectId 変更を effect で検知して同等の
  // flush + state リセットを 1 箇所で実行する。
  //
  // - 初回 mount: initRef.current.projectId === projectId なので no-op
  // - projectId 変化:
  //     1. 旧 project の pending PUT を flush
  //     2. 新 project の initial state を構築
  //     3. system.resetForProject を dispatch して reducer state を置換
  //     4. taskFallbackId も新 project の値で更新
  //     5. initRef.current を新 projectId で更新
  // - unmount: 最後に観測した projectId の pending を flush
  useEffect(() => {
    const cached = initRef.current
    if (cached === null) return // unreachable: 上の lazy init で必ず set 済み
    if (cached.projectId !== projectId) {
      // 旧 project の pending PUT を fire してから state を切り替える
      flushServerForProject(cached.projectId)
      const init = initializeWorkbench({
        projectId,
        searchParams: searchParamsRef.current,
      })
      if (init.hadUnknownValue) {
        // eslint-disable-next-line no-console
        console.warn(
          '[Workbench] URL contained unknown query value(s); using defaults',
        )
      }
      initRef.current = {
        projectId,
        state: init.state,
        taskFallbackId: init.taskFallbackId,
      }
      dispatchRaw({
        kind: 'system.resetForProject',
        tree: init.state.tree,
        lastUserActionAt: init.state.lastUserActionAt,
      })
      setTaskFallbackId(init.taskFallbackId)
    }
    return () => {
      // 後続の effect が走る (= projectId 変化) 場合、cached は今の
      // projectId なので「これから捨てる project」を flush する形に
      // なる。unmount 時 (最終 cleanup) も同様に最後の projectId が
      // flush される。
      flushServerForProject(cached.projectId)
    }
  }, [projectId])

  return {
    state: reducerState,
    dispatch,
    taskFallbackId,
    clearTaskFallback,
    setTaskFallbackId,
  }
}
