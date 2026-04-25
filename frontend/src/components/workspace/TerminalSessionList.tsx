import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Square, Trash2 } from 'lucide-react'
import { api } from '../../api/client'

interface SessionInfo {
  session_id: string
  started_at: number | null
  last_activity: number | null
  cmdline: string | null
  alive: boolean
}

interface SessionListResponse {
  sessions: SessionInfo[]
}

interface TerminalSessionListProps {
  agentId: string
}

const formatTimestamp = (epoch: number | null): string => {
  if (!epoch) return '—'
  const d = new Date(epoch * 1000)
  return d.toLocaleString()
}

const formatRelative = (epoch: number | null): string => {
  if (!epoch) return '—'
  const dt = Date.now() / 1000 - epoch
  if (dt < 60) return `${Math.floor(dt)}s ago`
  if (dt < 3600) return `${Math.floor(dt / 60)}m ago`
  if (dt < 86400) return `${Math.floor(dt / 3600)}h ago`
  return `${Math.floor(dt / 86400)}d ago`
}

export default function TerminalSessionList({ agentId }: TerminalSessionListProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data, isLoading, isError, error } = useQuery<SessionListResponse>({
    queryKey: ['terminal-sessions', agentId],
    queryFn: () =>
      api.get(`/workspaces/terminal/${agentId}/sessions`).then((r) => r.data),
    // Poll while the user is on the list view so a remote-killed
    // session disappears without a manual refresh.
    refetchInterval: 5_000,
  })

  const killMutation = useMutation({
    mutationFn: (sessionId: string) =>
      api.delete(`/workspaces/terminal/${agentId}/sessions/${sessionId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['terminal-sessions', agentId] })
    },
  })

  const handleNew = () => {
    // Open the WS without a session_id; the backend allocates one
    // and the TerminalPage's ``onSessionStarted`` callback rewrites
    // the URL once we receive it.
    navigate(`/workspaces/terminal/${agentId}/new`)
  }

  if (isLoading) {
    return (
      <div className="p-6 text-sm text-gray-400">Loading sessions…</div>
    )
  }
  if (isError) {
    return (
      <div className="p-6 text-sm text-red-400">
        Failed to load sessions:{' '}
        {(error as Error)?.message ?? 'unknown error'}
      </div>
    )
  }

  const sessions = data?.sessions ?? []

  return (
    <div className="flex flex-col h-full bg-gray-900 text-gray-200">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
        <h2 className="text-sm font-medium">
          Terminal sessions ({sessions.length})
        </h2>
        <button
          onClick={handleNew}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded bg-emerald-700 hover:bg-emerald-600"
        >
          <Plus className="w-3.5 h-3.5" />
          New session
        </button>
      </div>
      {sessions.length === 0 ? (
        <div className="p-6 text-sm text-gray-500">
          No sessions yet. Click <strong>New session</strong> to spawn one.
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="w-full text-xs">
            <thead className="bg-gray-800 text-gray-400 uppercase tracking-wide">
              <tr>
                <th className="px-3 py-2 text-left">Session ID</th>
                <th className="px-3 py-2 text-left">Shell</th>
                <th className="px-3 py-2 text-left">Started</th>
                <th className="px-3 py-2 text-left">Last activity</th>
                <th className="px-3 py-2 text-left">State</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => (
                <tr
                  key={s.session_id}
                  className="border-b border-gray-800 hover:bg-gray-800/40"
                >
                  <td className="px-3 py-2 font-mono">
                    <button
                      onClick={() =>
                        navigate(
                          `/workspaces/terminal/${agentId}/${s.session_id}`,
                        )
                      }
                      className="text-emerald-400 hover:text-emerald-300 hover:underline"
                    >
                      {s.session_id.slice(0, 12)}…
                    </button>
                  </td>
                  <td className="px-3 py-2 text-gray-400">
                    {s.cmdline ?? '—'}
                  </td>
                  <td
                    className="px-3 py-2 text-gray-400"
                    title={formatTimestamp(s.started_at)}
                  >
                    {formatRelative(s.started_at)}
                  </td>
                  <td
                    className="px-3 py-2 text-gray-400"
                    title={formatTimestamp(s.last_activity)}
                  >
                    {formatRelative(s.last_activity)}
                  </td>
                  <td className="px-3 py-2">
                    {s.alive ? (
                      <span className="inline-flex items-center gap-1 text-emerald-400">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                        alive
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-gray-500">
                        <Square className="w-3 h-3" />
                        exited
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      onClick={() => {
                        if (window.confirm(`Kill session ${s.session_id.slice(0, 12)}…?`)) {
                          killMutation.mutate(s.session_id)
                        }
                      }}
                      disabled={killMutation.isPending}
                      className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded text-red-400 hover:bg-red-900/40 disabled:opacity-40"
                    >
                      <Trash2 className="w-3 h-3" />
                      Kill
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
