import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  MessageSquarePlus,
  CheckCircle2,
  XCircle,
  Clock,
  ChevronDown,
  ChevronUp,
  ThumbsUp,
  ArrowRight,
} from 'lucide-react'
import { api } from '../../api/client'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type FeedbackItem = {
  id: string
  tool_name: string
  request_type: string
  description: string
  related_tools: string[]
  status: string
  votes: number
  submitted_by: string | null
  created_at: string
  updated_at: string
}

type FeedbackListResponse = {
  total: number
  items: FeedbackItem[]
}

type FeedbackSummaryResponse = {
  by_status: Record<string, number>
  by_type: { request_type: string; count: number }[]
  top_tools_with_open_requests: {
    tool_name: string
    open_count: number
    total_votes: number
  }[]
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STATUS_CONFIG: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  open: {
    label: 'Open',
    color: 'bg-status-progress/20 text-status-progress',
    icon: <Clock className="w-3 h-3" />,
  },
  accepted: {
    label: 'Accepted',
    color: 'bg-status-done/20 text-status-done',
    icon: <CheckCircle2 className="w-3 h-3" />,
  },
  rejected: {
    label: 'Rejected',
    color: 'bg-pri-urgent/20 text-pri-urgent',
    icon: <XCircle className="w-3 h-3" />,
  },
  done: {
    label: 'Done',
    color: 'bg-gray-700 text-gray-200',
    icon: <CheckCircle2 className="w-3 h-3" />,
  },
}

const TYPE_LABELS: Record<string, string> = {
  missing_param: 'パラメータ不足',
  merge: '統合',
  split: '分割',
  deprecate: '廃止',
  bug: 'バグ',
  performance: 'パフォーマンス',
  other: 'その他',
}

const STATUS_OPTIONS = ['open', 'accepted', 'rejected', 'done'] as const

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function McpFeedbackSection() {
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<string>('open')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const { data: summary } = useQuery<FeedbackSummaryResponse>({
    queryKey: ['mcp-feedback-summary'],
    queryFn: () => api.get('/mcp/usage/feedback/summary').then((r) => r.data),
  })

  const { data: feedbackList, isLoading } = useQuery<FeedbackListResponse>({
    queryKey: ['mcp-feedback-list', statusFilter],
    queryFn: () =>
      api
        .get(`/mcp/usage/feedback?status=${statusFilter}&limit=100`)
        .then((r) => r.data),
  })

  const updateMutation = useMutation({
    mutationFn: ({ id, params }: { id: string; params: string }) =>
      api.patch(`/mcp/usage/feedback/${id}?${params}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mcp-feedback-list'] })
      queryClient.invalidateQueries({ queryKey: ['mcp-feedback-summary'] })
    },
  })

  const handleStatusChange = (id: string, newStatus: string) => {
    updateMutation.mutate({ id, params: `status=${newStatus}` })
  }

  const handleVote = (id: string) => {
    updateMutation.mutate({ id, params: 'votes_delta=1' })
  }

  const totalOpen = summary?.by_status?.open ?? 0
  const totalAccepted = summary?.by_status?.accepted ?? 0
  const totalDone = summary?.by_status?.done ?? 0
  const totalRejected = summary?.by_status?.rejected ?? 0

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="font-serif text-base font-semibold text-gray-50">
          API 改善リクエスト
        </h2>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <FeedbackStatCard
          icon={<MessageSquarePlus className="w-4 h-4" />}
          label="Open"
          value={totalOpen}
          accent={totalOpen > 0 ? 'blue' : undefined}
        />
        <FeedbackStatCard
          icon={<CheckCircle2 className="w-4 h-4" />}
          label="Accepted"
          value={totalAccepted}
          accent={totalAccepted > 0 ? 'green' : undefined}
        />
        <FeedbackStatCard
          icon={<CheckCircle2 className="w-4 h-4" />}
          label="Done"
          value={totalDone}
        />
        <FeedbackStatCard
          icon={<XCircle className="w-4 h-4" />}
          label="Rejected"
          value={totalRejected}
        />
      </div>

      {/* Type breakdown + Top tools */}
      <div className="grid md:grid-cols-2 gap-4">
        {/* By type */}
        <div>
          <div className="text-xs font-semibold text-gray-200 uppercase mb-2">
            タイプ別件数
          </div>
          <div className="border border-line-2 rounded-very divide-y divide-line-1 bg-gray-800/30">
            {(!summary || summary.by_type.length === 0) && (
              <div className="px-3 py-4 text-center text-gray-200 text-sm">
                リクエストはありません
              </div>
            )}
            {summary?.by_type.map((t) => (
              <div
                key={t.request_type}
                className="px-3 py-2 flex items-center justify-between text-sm"
              >
                <span className="text-gray-50">
                  {TYPE_LABELS[t.request_type] ?? t.request_type}
                </span>
                <span className="tabular-nums text-gray-200">{t.count}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Top tools with open requests */}
        <div>
          <div className="text-xs font-semibold text-gray-200 uppercase mb-2">
            リクエストが多いツール
          </div>
          <div className="border border-line-2 rounded-very divide-y divide-line-1 bg-gray-800/30">
            {(!summary || summary.top_tools_with_open_requests.length === 0) && (
              <div className="px-3 py-4 text-center text-gray-200 text-sm">
                Open なリクエストはありません
              </div>
            )}
            {summary?.top_tools_with_open_requests.map((t) => (
              <div
                key={t.tool_name}
                className="px-3 py-2 flex items-center justify-between text-sm"
              >
                <span className="font-mono text-xs text-gray-50">
                  {t.tool_name}
                </span>
                <div className="flex items-center gap-2">
                  <span className="tabular-nums text-gray-200">
                    {t.open_count}件
                  </span>
                  <span className="tabular-nums text-gray-200 text-xs flex items-center gap-0.5">
                    <ThumbsUp className="w-3 h-3" />
                    {t.total_votes}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Feedback list */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs font-semibold text-gray-200 uppercase">
            リクエスト一覧
          </div>
          <div className="flex gap-1 text-xs">
            {STATUS_OPTIONS.map((s) => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                className={`px-2.5 py-1 rounded border ${
                  statusFilter === s
                    ? 'bg-accent-500 text-gray-50 border-accent-400'
                    : 'border-line-2 text-gray-100 hover:bg-gray-700'
                }`}
              >
                {STATUS_CONFIG[s]?.label ?? s}
              </button>
            ))}
          </div>
        </div>

        <div className="border border-line-2 rounded-very divide-y divide-line-1 bg-gray-800/30">
          {isLoading && (
            <div className="px-3 py-6 text-center text-gray-200">読み込み中...</div>
          )}
          {!isLoading && (!feedbackList || feedbackList.items.length === 0) && (
            <div className="px-3 py-6 text-center text-gray-200 text-sm">
              {statusFilter === 'open' ? 'Open なリクエストはありません' : '該当するリクエストはありません'}
            </div>
          )}
          {feedbackList?.items.map((item) => {
            const isExpanded = expandedId === item.id
            const cfg = STATUS_CONFIG[item.status]

            return (
              <div key={item.id} className="group">
                {/* Summary row */}
                <div
                  className="px-3 py-2.5 flex items-center gap-3 cursor-pointer hover:bg-gray-700/40"
                  onClick={() => setExpandedId(isExpanded ? null : item.id)}
                >
                  <div className="flex-shrink-0">
                    {isExpanded ? (
                      <ChevronUp className="w-4 h-4 text-gray-200" />
                    ) : (
                      <ChevronDown className="w-4 h-4 text-gray-200" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="font-mono text-xs font-medium text-gray-50">
                        {item.tool_name}
                      </span>
                      {item.related_tools.length > 0 && (
                        <span className="text-gray-200 flex items-center gap-1 text-xs">
                          <ArrowRight className="w-3 h-3" />
                          {item.related_tools.join(', ')}
                        </span>
                      )}
                    </div>
                    <div className="text-sm text-gray-200 truncate">
                      {item.description}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <span className="text-xs px-2 py-0.5 rounded-full bg-gray-700 text-gray-200">
                      {TYPE_LABELS[item.request_type] ?? item.request_type}
                    </span>
                    {cfg && (
                      <span
                        className={`text-xs px-2 py-0.5 rounded-full flex items-center gap-1 ${cfg.color}`}
                      >
                        {cfg.icon}
                        {cfg.label}
                      </span>
                    )}
                    <span className="text-xs text-gray-200 tabular-nums flex items-center gap-0.5">
                      <ThumbsUp className="w-3 h-3" />
                      {item.votes}
                    </span>
                  </div>
                </div>

                {/* Expanded detail */}
                {isExpanded && (
                  <div className="px-3 pb-3 pl-10 space-y-3">
                    <div className="text-sm text-gray-50 whitespace-pre-wrap bg-gray-800 rounded-comfortable p-3">
                      {item.description}
                    </div>
                    <div className="flex items-center gap-4 text-xs text-gray-200">
                      <span>
                        送信: {new Date(item.created_at).toLocaleString('ja-JP')}
                      </span>
                      {item.submitted_by && (
                        <span className="font-mono">{item.submitted_by.slice(0, 16)}...</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleVote(item.id)
                        }}
                        className="text-xs px-2.5 py-1 rounded border border-line-2 text-gray-100 hover:bg-gray-700 flex items-center gap-1"
                      >
                        <ThumbsUp className="w-3 h-3" />
                        +1
                      </button>
                      <div className="border-l border-line-2 h-4" />
                      {item.status !== 'accepted' && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            handleStatusChange(item.id, 'accepted')
                          }}
                          className="text-xs px-2.5 py-1 rounded bg-status-done/20 text-status-done hover:bg-status-done/30"
                        >
                          Accept
                        </button>
                      )}
                      {item.status !== 'rejected' && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            handleStatusChange(item.id, 'rejected')
                          }}
                          className="text-xs px-2.5 py-1 rounded bg-pri-urgent/20 text-pri-urgent hover:bg-pri-urgent/30"
                        >
                          Reject
                        </button>
                      )}
                      {item.status !== 'done' && item.status !== 'open' && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            handleStatusChange(item.id, 'done')
                          }}
                          className="text-xs px-2.5 py-1 rounded bg-gray-700 text-gray-200 hover:bg-gray-600"
                        >
                          Done
                        </button>
                      )}
                      {item.status !== 'open' && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            handleStatusChange(item.id, 'open')
                          }}
                          className="text-xs px-2.5 py-1 rounded bg-status-progress/20 text-status-progress hover:bg-status-progress/30"
                        >
                          Reopen
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {feedbackList && feedbackList.total > feedbackList.items.length && (
          <div className="text-xs text-gray-200 mt-2 text-center">
            {feedbackList.total} 件中 {feedbackList.items.length} 件を表示
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Stat card
// ---------------------------------------------------------------------------

function FeedbackStatCard({
  icon,
  label,
  value,
  accent,
}: {
  icon: React.ReactNode
  label: string
  value: number
  accent?: 'blue' | 'green'
}) {
  const accentClass =
    accent === 'blue'
      ? 'text-status-progress'
      : accent === 'green'
        ? 'text-status-done'
        : 'text-gray-50'
  return (
    <div className="border border-line-2 rounded-very p-3 bg-gray-800/30">
      <div className="flex items-center gap-1.5 text-xs text-gray-200 mb-1">
        {icon}
        {label}
      </div>
      <div className={`text-2xl font-semibold tabular-nums ${accentClass}`}>
        {value.toLocaleString()}
      </div>
    </div>
  )
}
