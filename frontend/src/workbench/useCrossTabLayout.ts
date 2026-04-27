/**
 * Phase 6.1: React 18 idiomatic な cross-tab layout 購読 hook.
 *
 * `subscribeCrossTab` と `getCrossTabSnapshot` を `useSyncExternalStore`
 * に橋渡しする. 初期 mount では `null` を返し、別タブが localStorage
 * に layout を書いた時 (= storage event 発火時) のみ snapshot が
 * 非 null の新しい reference に変化する. consumer (WorkbenchPage) は
 * snapshot 変化を `useEffect` で観測して `remote.crossTab` action を
 * dispatch する.
 *
 * 不変条件:
 *   - 初期 mount で dispatch しない (v1 の useEffect+subscribe と同等)
 *   - I-7 stamp guard は reducer 側で維持 (lastUserActionAt > stamp)
 *   - getSnapshot は同一 storage 状態に対して同一 reference を返す
 *     (Map.get の参照安定性で担保)
 *   - writer-tab には storage event が飛ばない browser 仕様は不変
 */
import { useCallback, useSyncExternalStore } from 'react'
import {
  getCrossTabSnapshot,
  subscribeCrossTab,
  type CrossTabSnapshot,
} from './storage'
import type { PaneType } from './types'

export function useCrossTabLayout(
  projectId: string,
  knownPaneTypes: Set<PaneType>,
): CrossTabSnapshot | null {
  const subscribe = useCallback(
    (listener: () => void) =>
      subscribeCrossTab(projectId, knownPaneTypes, listener),
    [projectId, knownPaneTypes],
  )
  const getSnapshot = useCallback(
    () => getCrossTabSnapshot(projectId),
    [projectId],
  )
  return useSyncExternalStore(subscribe, getSnapshot, () => null)
}
