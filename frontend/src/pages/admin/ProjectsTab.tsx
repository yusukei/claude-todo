import { useState, useRef, useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Pencil, Check, X } from 'lucide-react'
import { api } from '../../api/client'
import { showConfirm } from '../../components/common/ConfirmDialog'
import { showErrorToast } from '../../components/common/Toast'
import type { Project } from '../../types'

export default function ProjectsTab() {
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [color, setColor] = useState('#6366f1')

  const { data: projects = [] } = useQuery({
    queryKey: ['admin-projects'],
    queryFn: () => api.get('/projects').then((r) => r.data),
  })

  const create = useMutation({
    mutationFn: () => api.post('/projects', { name, description, color }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-projects'] })
      qc.invalidateQueries({ queryKey: ['projects'] })
      setName(''); setDescription(''); setColor('#6366f1'); setShowForm(false)
    },
    onError: () => showErrorToast('プロジェクトの作成に失敗しました'),
  })

  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const renameInputRef = useRef<HTMLInputElement>(null)

  const rename = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => api.patch(`/projects/${id}`, { name }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-projects'] })
      qc.invalidateQueries({ queryKey: ['projects'] })
      setRenamingId(null)
    },
    onError: () => showErrorToast('プロジェクト名の変更に失敗しました'),
  })

  const startRename = (p: Project) => {
    setRenamingId(p.id)
    setRenameValue(p.name)
  }

  useEffect(() => {
    if (renamingId && renameInputRef.current) {
      renameInputRef.current.focus()
      renameInputRef.current.select()
    }
  }, [renamingId])

  const confirmRename = (id: string, originalName: string) => {
    const trimmed = renameValue.trim()
    if (trimmed && trimmed !== originalName) {
      rename.mutate({ id, name: trimmed })
    } else {
      setRenamingId(null)
    }
  }

  const archive = useMutation({
    mutationFn: (id: string) => api.patch(`/projects/${id}`, { status: 'archived' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-projects'] })
      qc.invalidateQueries({ queryKey: ['projects'] })
    },
    onError: () => showErrorToast('プロジェクトのアーカイブに失敗しました'),
  })

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-serif text-base font-semibold text-gray-50">プロジェクト管理</h2>
        <button
          onClick={() => setShowForm((v) => !v)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-accent-500 text-gray-50 rounded-comfortable hover:bg-accent-400"
        >
          <Plus className="w-4 h-4" />プロジェクト追加
        </button>
      </div>

      {showForm && (
        <div className="mb-4 p-4 border border-line-2 rounded-very bg-gray-800/30 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <input
              placeholder="プロジェクト名"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="border border-line-2 rounded-comfortable px-3 py-2 text-sm bg-gray-900 text-gray-50 placeholder:text-gray-200 focus:outline-none focus:ring-2 focus:ring-focus focus:border-accent-400"
            />
            <div className="flex items-center gap-2">
              <label className="text-sm text-gray-100">カラー</label>
              <input
                type="color"
                value={color}
                onChange={(e) => setColor(e.target.value)}
                className="w-8 h-8 rounded cursor-pointer border-0"
              />
              <span className="text-xs text-gray-200">{color}</span>
            </div>
            <input
              placeholder="説明（任意）"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="col-span-2 border border-line-2 rounded-comfortable px-3 py-2 text-sm bg-gray-900 text-gray-50 placeholder:text-gray-200 focus:outline-none focus:ring-2 focus:ring-focus focus:border-accent-400"
            />
          </div>
          <div className="flex justify-end gap-2">
            <button onClick={() => setShowForm(false)} className="px-3 py-1.5 text-sm border border-line-2 text-gray-100 rounded-comfortable hover:bg-gray-700">キャンセル</button>
            <button
              onClick={() => create.mutate()}
              disabled={!name || create.isPending}
              className="px-3 py-1.5 text-sm bg-accent-500 text-gray-50 rounded-comfortable hover:bg-accent-400 disabled:opacity-50"
            >
              {create.isPending ? '作成中...' : '作成'}
            </button>
          </div>
        </div>
      )}

      <div className="border border-line-2 rounded-very overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-800/60 text-[11px] uppercase tracking-[0.08em] text-gray-200">
            <tr>
              <th className="px-4 py-3 text-left font-medium">プロジェクト</th>
              <th className="px-4 py-3 text-left font-medium">説明</th>
              <th className="px-4 py-3 text-center font-medium">メンバー</th>
              <th className="px-4 py-3 text-center font-medium">ステータス</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-line-1 bg-gray-800/30">
            {projects.map((p: Project) => (
              <tr key={p.id} className="hover:bg-gray-700/40">
                <td className="px-4 py-3">
                  {renamingId === p.id ? (
                    <div className="flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: p.color ?? undefined }} />
                      <input
                        ref={renameInputRef}
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') confirmRename(p.id, p.name)
                          if (e.key === 'Escape') setRenamingId(null)
                        }}
                        maxLength={255}
                        className="font-medium text-sm text-gray-50 bg-gray-900 border border-accent-400 rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-focus"
                      />
                      <button onClick={() => confirmRename(p.id, p.name)} disabled={rename.isPending} className="p-0.5 text-status-done hover:bg-status-done/20 rounded" title="確定">
                        <Check className="w-4 h-4" />
                      </button>
                      <button onClick={() => setRenamingId(null)} className="p-0.5 text-gray-200 hover:bg-gray-700 rounded" title="キャンセル">
                        <X className="w-4 h-4" />
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 group">
                      <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: p.color ?? undefined }} />
                      <span className="font-medium text-gray-50">{p.name}</span>
                      <button
                        onClick={() => startRename(p)}
                        className="p-0.5 text-gray-300 opacity-0 group-hover:opacity-100 hover:text-accent-400 transition-opacity rounded"
                        title="リネーム"
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-200 truncate max-w-xs">{p.description || '—'}</td>
                <td className="px-4 py-3 text-center text-gray-200">{p.members?.length ?? 0}</td>
                <td className="px-4 py-3 text-center">
                  <span className={`px-2 py-0.5 text-xs rounded-full font-medium ${p.status === 'active' ? 'bg-status-done/20 text-status-done' : 'bg-gray-700 text-gray-200'}`}>
                    {p.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-right">
                  {p.status === 'active' && (
                    <button
                      onClick={async () => { if (await showConfirm(`"${p.name}" をアーカイブしますか？`)) archive.mutate(p.id) }}
                      className="text-xs text-gray-300 hover:text-pri-urgent"
                    >
                      アーカイブ
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
