import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2, Plus } from 'lucide-react'
import { api } from '../../api/client'
import { showErrorToast } from '../../components/common/Toast'
import type { AllowedEmail } from '../../types'

export default function AllowedEmailsTab() {
  const qc = useQueryClient()
  const [email, setEmail] = useState('')

  const { data: entries = [] } = useQuery({
    queryKey: ['admin-allowed-emails'],
    queryFn: () => api.get('/users/allowed-emails/').then((r) => r.data),
  })

  const add = useMutation({
    mutationFn: () => api.post('/users/allowed-emails/', { email }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-allowed-emails'] })
      setEmail('')
    },
    onError: () => showErrorToast('許可メールの追加に失敗しました'),
  })

  const del = useMutation({
    mutationFn: (id: string) => api.delete(`/users/allowed-emails/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-allowed-emails'] }),
    onError: () => showErrorToast('許可メールの削除に失敗しました'),
  })

  return (
    <div>
      <h2 className="mb-4 font-serif text-base font-semibold text-gray-50">
        Google OAuth 許可メール
      </h2>
      <div className="mb-4 flex gap-2">
        <input
          placeholder="example@gmail.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && email && add.mutate()}
          className="flex-1 rounded-comfortable border border-line-2 bg-gray-900 px-3 py-2 text-sm text-gray-50 placeholder:text-gray-200 focus:border-accent-400 focus:outline-none focus:ring-2 focus:ring-focus"
        />
        <button
          onClick={() => add.mutate()}
          disabled={!email || add.isPending}
          className="inline-flex items-center gap-1.5 rounded-comfortable bg-accent-500 px-3 py-2 text-sm font-medium text-gray-50 hover:bg-accent-400 disabled:opacity-50"
        >
          <Plus className="h-4 w-4" />
          追加
        </button>
      </div>
      <div className="overflow-hidden rounded-very border border-line-2">
        <table className="w-full text-sm">
          <thead className="bg-gray-800/60 text-[11px] uppercase tracking-[0.08em] text-gray-200">
            <tr>
              <th className="px-4 py-3 text-left font-medium">メールアドレス</th>
              <th className="px-4 py-3 text-left font-medium">登録日</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-line-1 bg-gray-800/30">
            {entries.map((e: AllowedEmail) => (
              <tr key={e.id} className="hover:bg-gray-700/40">
                <td className="px-4 py-3 font-mono text-[13px] text-gray-50">
                  {e.email}
                </td>
                <td className="px-4 py-3 text-gray-200">
                  {new Date(e.created_at).toLocaleDateString('ja-JP')}
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    onClick={() => del.mutate(e.id)}
                    className="text-gray-300 hover:text-pri-urgent"
                    aria-label="削除"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </td>
              </tr>
            ))}
            {entries.length === 0 && (
              <tr>
                <td
                  colSpan={3}
                  className="px-4 py-8 text-center text-sm text-gray-200"
                >
                  許可メールがありません
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
