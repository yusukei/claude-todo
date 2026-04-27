import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Activity, X } from 'lucide-react'
import clsx from 'clsx'
import { api } from '../../api/client'

interface LiveTask {
  id: string
  title: string
  active_form: string | null
  assignee_id: string | null
  project_id: string
  project_name: string
  updated_at: string
  created_at: string
}

function formatElapsed(isoTimestamp: string): string {
  const then = new Date(isoTimestamp).getTime()
  const now = Date.now()
  const seconds = Math.max(0, Math.floor((now - then) / 1000))
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h`
  const days = Math.floor(hours / 24)
  return `${days}d`
}

/**
 * Cross-project live activity panel (Sprint 2 / S2-8).
 *
 * Floating bottom-right toggle that opens a slide-up panel listing every
 * in-progress task the user can access, newest first. SSE invalidations
 * (`useSSE` → task.updated) refresh the list automatically; we also refetch
 * every 15s as a safety net so elapsed timers stay roughly accurate.
 */
export default function LiveActivityPanel() {
  const [open, setOpen] = useState(false)

  const { data: tasks = [] } = useQuery<LiveTask[]>({
    queryKey: ['tasks', 'live'],
    queryFn: () => api.get<LiveTask[]>('/tasks/live').then((r) => r.data),
    // Cheap endpoint (in_progress only, bounded) — a 15s refetch keeps the
    // elapsed-time labels roughly current without SSE payload churn.
    refetchInterval: 15_000,
    staleTime: 10_000,
  })

  const count = tasks.length

  return (
    <>
      <button
        onClick={() => setOpen(!open)}
        aria-label="ライブアクティビティ"
        title={`ライブアクティビティ (${count})`}
        className={clsx(
          'fixed bottom-4 right-4 z-30 flex items-center gap-2 px-3 py-2 rounded-full shadow-whisper transition-all border',
          count > 0
            ? 'bg-accent-500 text-gray-50 border-accent-400 hover:bg-accent-400'
            : 'bg-gray-700 text-gray-200 border-line-2 hover:bg-gray-600',
        )}
      >
        <Activity
          className={clsx('w-4 h-4', count > 0 && 'animate-pulse')}
          aria-hidden
        />
        <span className="text-sm font-medium">{count}</span>
      </button>

      {open && (
        <div
          className="fixed bottom-16 right-4 z-30 w-96 max-h-[70vh] bg-gray-800 rounded-very shadow-whisper border border-line-2 flex flex-col"
          role="dialog"
          aria-label="ライブアクティビティ"
        >
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-line-2">
            <div className="flex items-center gap-2">
              <Activity className="w-4 h-4 text-accent-400" />
              <h3 className="text-sm font-medium text-gray-50 font-serif">
                ライブアクティビティ
              </h3>
              <span className="text-xs text-gray-300 font-mono">{count} 件</span>
            </div>
            <button
              onClick={() => setOpen(false)}
              className="p-1 rounded text-gray-300 hover:text-gray-50"
              aria-label="閉じる"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto">
            {tasks.length === 0 ? (
              <p className="text-sm text-gray-300 px-4 py-8 text-center">
                進行中のタスクはありません
              </p>
            ) : (
              <ul className="divide-y divide-line-1">
                {tasks.map((t) => (
                  <li key={t.id}>
                    <Link
                      to={`/projects/${t.project_id}?task=${t.id}`}
                      onClick={() => setOpen(false)}
                      className="block px-4 py-2.5 hover:bg-gray-700 transition-colors"
                    >
                      <div className="flex items-center justify-between gap-2 mb-0.5">
                        <span className="text-sm font-medium text-gray-50 truncate">
                          {t.title}
                        </span>
                        <span className="text-xs text-gray-300 flex-shrink-0 font-mono">
                          {formatElapsed(t.updated_at)}
                        </span>
                      </div>
                      {t.active_form && (
                        <p className="text-xs text-accent-300 truncate font-mono">
                          {t.active_form}
                        </p>
                      )}
                      <p className="text-xs text-gray-300 truncate">
                        {t.project_name}
                      </p>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </>
  )
}
