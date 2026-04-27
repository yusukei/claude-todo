import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Fingerprint, Trash2, Plus, ShieldCheck, ShieldOff } from 'lucide-react'
import { startRegistration } from '@simplewebauthn/browser'
import { api } from '../../api/client'
import { useAuthStore } from '../../store/auth'
import { showErrorToast, showSuccessToast } from '../../components/common/Toast'
import type { WebAuthnCredentialInfo } from '../../types'

export default function PasskeysTab() {
  const qc = useQueryClient()
  const user = useAuthStore((s) => s.user)
  const setUser = useAuthStore((s) => s.setUser)
  const [name, setName] = useState('')
  const [registering, setRegistering] = useState(false)

  const { data: credentials = [] } = useQuery<WebAuthnCredentialInfo[]>({
    queryKey: ['webauthn-credentials'],
    queryFn: () => api.get('/auth/webauthn/credentials').then((r) => r.data),
  })

  const remove = useMutation({
    mutationFn: (credentialId: string) =>
      api.delete(`/auth/webauthn/credentials/${encodeURIComponent(credentialId)}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['webauthn-credentials'] })
      refreshUser()
      showSuccessToast('パスキーを削除しました')
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      showErrorToast(msg || 'パスキーの削除に失敗しました')
    },
  })

  const togglePassword = useMutation({
    mutationFn: (disabled: boolean) =>
      api.patch('/auth/webauthn/password-disabled', { disabled }),
    onSuccess: (_data, disabled) => {
      refreshUser()
      showSuccessToast(disabled ? 'パスワードログインを無効にしました' : 'パスワードログインを有効にしました')
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      showErrorToast(msg || 'パスワード設定の変更に失敗しました')
    },
  })

  const refreshUser = () => {
    api.get('/auth/me').then((r) => setUser(r.data))
  }

  const handleRegister = async () => {
    setRegistering(true)
    try {
      const { data: options } = await api.post('/auth/webauthn/register/options')
      const credential = await startRegistration({ optionsJSON: options })
      await api.post('/auth/webauthn/register/verify', {
        credential,
        name: name || undefined,
      })
      qc.invalidateQueries({ queryKey: ['webauthn-credentials'] })
      refreshUser()
      setName('')
      showSuccessToast('パスキーを登録しました')
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'NotAllowedError') return
      showErrorToast('パスキーの登録に失敗しました')
    } finally {
      setRegistering(false)
    }
  }

  const passwordDisabled = user?.password_disabled ?? false
  const hasCredentials = credentials.length > 0

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-serif text-lg font-semibold text-gray-50 mb-1">パスキー管理</h2>
        <p className="text-sm text-gray-200">
          パスキーを登録すると、パスワードなしでログインできます。
        </p>
      </div>

      {/* Register new passkey */}
      <div className="flex gap-2">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="パスキーの名前（任意）"
          className="flex-1 border border-line-2 rounded-comfortable px-3 py-2 text-sm bg-gray-900 text-gray-50 placeholder:text-gray-200 focus:outline-none focus:ring-2 focus:ring-focus focus:border-accent-400"
        />
        <button
          onClick={handleRegister}
          disabled={registering}
          className="flex items-center gap-1.5 bg-accent-500 text-gray-50 px-4 py-2 rounded-comfortable hover:bg-accent-400 disabled:opacity-50 text-sm font-medium"
        >
          <Plus className="w-4 h-4" />
          {registering ? '登録中...' : 'パスキーを登録'}
        </button>
      </div>

      {/* List credentials */}
      {credentials.length === 0 ? (
        <p className="text-sm text-gray-200 py-4 text-center">
          登録済みのパスキーはありません
        </p>
      ) : (
        <ul className="divide-y divide-line-1">
          {credentials.map((cred) => (
            <li key={cred.credential_id} className="flex items-center justify-between py-3">
              <div className="flex items-center gap-3">
                <Fingerprint className="w-5 h-5 text-accent-500" />
                <div>
                  <p className="text-sm font-medium text-gray-50">{cred.name}</p>
                  <p className="text-xs text-gray-200">
                    登録日: {new Date(cred.created_at).toLocaleDateString('ja-JP')}
                  </p>
                </div>
              </div>
              <button
                onClick={() => remove.mutate(cred.credential_id)}
                className="p-1.5 text-gray-300 hover:text-pri-urgent"
                title="削除"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* Password toggle */}
      {hasCredentials && (
        <div className="border-t border-line-2 pt-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {passwordDisabled
                ? <ShieldCheck className="w-5 h-5 text-status-done" />
                : <ShieldOff className="w-5 h-5 text-gray-200" />
              }
              <div>
                <p className="text-sm font-medium text-gray-50">
                  パスワードログイン
                </p>
                <p className="text-xs text-gray-200">
                  {passwordDisabled
                    ? '無効 — パスキーのみでログインします'
                    : '有効 — パスワードとパスキーの両方でログインできます'
                  }
                </p>
              </div>
            </div>
            <button
              onClick={() => togglePassword.mutate(!passwordDisabled)}
              disabled={togglePassword.isPending}
              className={`px-4 py-1.5 rounded-comfortable text-sm font-medium transition-colors ${
                passwordDisabled
                  ? 'bg-gray-700 text-gray-50 hover:bg-gray-600'
                  : 'bg-pri-urgent/20 text-pri-urgent hover:bg-pri-urgent/30'
              } disabled:opacity-50`}
            >
              {passwordDisabled ? 'パスワードを有効にする' : 'パスワードを無効にする'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
