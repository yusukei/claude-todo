import { useState, useRef, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Check, X, Pencil, Lock, Unlock } from 'lucide-react'
import { api } from '../api/client'
import { useAuthStore } from '../store/auth'
import ProjectMembersTab from '../components/project/ProjectMembersTab'
import { showErrorToast } from '../components/common/Toast'

const COLOR_PRESETS = [
  '#6366f1', '#8b5cf6', '#ec4899', '#ef4444', '#f97316',
  '#eab308', '#22c55e', '#14b8a6', '#06b6d4', '#3b82f6',
]

export default function ProjectSettingsPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const qc = useQueryClient()
  const user = useAuthStore((s) => s.user)

  const { data: project } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.get(`/projects/${projectId}`).then((r) => r.data),
    enabled: !!projectId,
  })

  const isOwnerOrAdmin =
    user?.is_admin ||
    project?.members?.some((m: { user_id: string; role: string }) => m.user_id === user?.id && m.role === 'owner')

  // ── Rename ───────────────────────────────────────────
  const [isRenaming, setIsRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState('')
  const renameInputRef = useRef<HTMLInputElement>(null)

  const renameMutation = useMutation({
    mutationFn: (name: string) => api.patch(`/projects/${projectId}`, { name }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['project', projectId] })
      qc.invalidateQueries({ queryKey: ['projects'] })
      setIsRenaming(false)
    },
    onError: () => showErrorToast('プロジェクト名の変更に失敗しました'),
  })

  const startRename = () => {
    if (!project) return
    setRenameValue(project.name)
    setIsRenaming(true)
  }

  useEffect(() => {
    if (isRenaming && renameInputRef.current) {
      renameInputRef.current.focus()
      renameInputRef.current.select()
    }
  }, [isRenaming])

  const confirmRename = () => {
    const trimmed = renameValue.trim()
    if (trimmed && trimmed !== project?.name) {
      renameMutation.mutate(trimmed)
    } else {
      setIsRenaming(false)
    }
  }

  // ── Color ────────────────────────────────────────────
  const colorMutation = useMutation({
    mutationFn: (color: string) => api.patch(`/projects/${projectId}`, { color }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['project', projectId] })
      qc.invalidateQueries({ queryKey: ['projects'] })
    },
    onError: () => showErrorToast('カラーの変更に失敗しました'),
  })

  // ── Lock ─────────────────────────────────────────────
  const lockMutation = useMutation({
    mutationFn: (locked: boolean) => api.patch(`/projects/${projectId}`, { is_locked: locked }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['project', projectId] })
      qc.invalidateQueries({ queryKey: ['projects'] })
    },
    onError: () => showErrorToast('ロック状態の変更に失敗しました'),
  })

  if (!project) return <div className="p-8 text-gray-500 dark:text-gray-400">読み込み中...</div>

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto p-8 space-y-8">
        {/* Header */}
        <div className="flex items-center gap-3">
          <Link
            to={`/projects/${projectId}`}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
            title="プロジェクトに戻る"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="text-xl font-bold text-gray-800 dark:text-gray-100">プロジェクト設定</h1>
            <p className="text-sm text-gray-500 dark:text-gray-400">{project.name}</p>
          </div>
        </div>

        {/* General settings */}
        <section className="space-y-4">
          <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-100">基本設定</h2>
          <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 divide-y divide-gray-100 dark:divide-gray-700">
            {/* Project name */}
            <div className="px-6 py-4 flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-700 dark:text-gray-300">プロジェクト名</p>
                {isRenaming ? (
                  <div className="flex items-center gap-2 mt-1">
                    <input
                      ref={renameInputRef}
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') confirmRename()
                        if (e.key === 'Escape') setIsRenaming(false)
                      }}
                      maxLength={255}
                      className="bg-white dark:bg-gray-700 border border-indigo-400 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 text-gray-900 dark:text-gray-100"
                    />
                    <button onClick={confirmRename} disabled={renameMutation.isPending} className="p-1 text-green-600 hover:bg-green-50 dark:hover:bg-green-900/30 rounded">
                      <Check className="w-4 h-4" />
                    </button>
                    <button onClick={() => setIsRenaming(false)} className="p-1 text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded">
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                ) : (
                  <p className="text-sm text-gray-500 dark:text-gray-400 mt-0.5">{project.name}</p>
                )}
              </div>
              {!isRenaming && isOwnerOrAdmin && (
                <button
                  onClick={startRename}
                  className="p-2 text-gray-400 hover:text-indigo-500 dark:hover:text-indigo-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
                >
                  <Pencil className="w-4 h-4" />
                </button>
              )}
            </div>

            {/* Color */}
            <div className="px-6 py-4">
              <p className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">カラー</p>
              <div className="flex items-center gap-2">
                {COLOR_PRESETS.map((c) => (
                  <button
                    key={c}
                    onClick={() => isOwnerOrAdmin && colorMutation.mutate(c)}
                    disabled={!isOwnerOrAdmin}
                    className={`w-7 h-7 rounded-full border-2 transition-all ${
                      project.color === c
                        ? 'border-gray-800 dark:border-white scale-110'
                        : 'border-transparent hover:scale-110'
                    } ${!isOwnerOrAdmin ? 'cursor-default' : 'cursor-pointer'}`}
                    style={{ backgroundColor: c }}
                  />
                ))}
              </div>
            </div>

            {/* Lock */}
            {isOwnerOrAdmin && (
              <div className="px-6 py-4 flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-700 dark:text-gray-300">プロジェクトロック</p>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                    ロック中はタスクの作成・編集ができません
                  </p>
                </div>
                <button
                  onClick={() => lockMutation.mutate(!project.is_locked)}
                  disabled={lockMutation.isPending}
                  className={`flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium rounded-lg transition-colors ${
                    project.is_locked
                      ? 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-400 hover:bg-amber-200 dark:hover:bg-amber-900/60'
                      : 'bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-600'
                  }`}
                >
                  {project.is_locked ? <Lock className="w-4 h-4" /> : <Unlock className="w-4 h-4" />}
                  {project.is_locked ? 'ロック中' : 'アンロック'}
                </button>
              </div>
            )}
          </div>
        </section>

        {/* Members */}
        <section>
          <ProjectMembersTab project={project} />
        </section>
      </div>
    </div>
  )
}
