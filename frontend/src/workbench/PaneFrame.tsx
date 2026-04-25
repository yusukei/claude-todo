import ErrorBoundary from '../components/common/ErrorBoundary'
import { AlertTriangle } from 'lucide-react'
import type { Pane } from './types'
import { getPaneComponent } from './paneRegistry'

interface Props {
  pane: Pane
  projectId: string
  onConfigChange: (paneId: string, patch: Record<string, unknown>) => void
}

/**
 * Wrap a single pane with an ErrorBoundary so a render-time crash in
 * one pane (e.g. a bad doc id throwing in DocPane) does not bring
 * down the entire Workbench. The fallback shows the error and a
 * reset hint; the user can change the pane type or close the tab to
 * recover.
 */
export default function PaneFrame({ pane, projectId, onConfigChange }: Props) {
  const Component = getPaneComponent(pane.paneType)
  return (
    <div className="flex-1 min-h-0 overflow-hidden bg-white dark:bg-gray-900">
      <ErrorBoundary fallback={<PaneCrashFallback />}>
        <Component
          projectId={projectId}
          paneConfig={pane.paneConfig}
          onConfigChange={(patch) => onConfigChange(pane.id, patch)}
        />
      </ErrorBoundary>
    </div>
  )
}

function PaneCrashFallback() {
  return (
    <div className="h-full flex flex-col items-center justify-center gap-3 p-6 text-center bg-red-50 dark:bg-red-950/30">
      <AlertTriangle className="w-8 h-8 text-red-500" />
      <p className="text-sm text-red-700 dark:text-red-300 font-medium">
        This pane crashed.
      </p>
      <p className="text-xs text-red-600 dark:text-red-400 max-w-md">
        Open the browser console for the stack trace. Closing or
        switching the pane type recovers; the rest of the Workbench
        is unaffected.
      </p>
    </div>
  )
}
