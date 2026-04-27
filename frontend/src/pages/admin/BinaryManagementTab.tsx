import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2, Upload, Bot, ServerCog } from 'lucide-react'
import { api } from '../../api/client'
import { showErrorToast, showSuccessToast } from '../../components/common/Toast'

/**
 * Binary release management.
 *
 * Two sub-surfaces share the same shape (list + upload + delete) but
 * hit independent endpoints:
 *   - Agent:      /api/v1/workspaces/releases
 *   - Supervisor: /api/v1/workspaces/supervisor-releases
 */

type Kind = 'agent' | 'supervisor'

interface Release {
  id: string
  version: string
  os_type: 'win32' | 'linux' | 'darwin'
  arch: string
  channel: 'stable' | 'beta' | 'canary'
  sha256: string
  size_bytes: number
  release_notes: string
  uploaded_by: string
  created_at: string
  download_url?: string
}

const ENDPOINTS: Record<Kind, string> = {
  agent: '/workspaces/releases',
  supervisor: '/workspaces/supervisor-releases',
}

const KIND_LABELS: Record<Kind, string> = {
  agent: 'Agent',
  supervisor: 'Supervisor',
}

const OS_OPTIONS: Array<{ value: Release['os_type']; label: string }> = [
  { value: 'win32', label: 'Windows (win32)' },
  { value: 'linux', label: 'Linux' },
  { value: 'darwin', label: 'macOS (darwin)' },
]

const CHANNEL_OPTIONS: Array<{ value: Release['channel']; label: string }> = [
  { value: 'stable', label: 'stable' },
  { value: 'beta', label: 'beta' },
  { value: 'canary', label: 'canary' },
]

const ARCH_OPTIONS = ['x64', 'arm64', 'x86']

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${bytes} B`
}

export default function BinaryManagementTab() {
  const [kind, setKind] = useState<Kind>('agent')
  return (
    <div>
      <h2 className="font-serif text-base font-semibold text-gray-50 mb-1">
        バイナリ管理
      </h2>
      <p className="text-xs text-gray-200 mb-4">
        各リモートホストに配布する Agent / Supervisor の実行ファイルを登録・削除します。
        登録した最新バージョンは接続時に自動配信され、各ホストが安全な手順 (sha256 検証 + atomic swap) で更新します。
      </p>

      {/* Kind tabs */}
      <div className="flex gap-1 mb-4 border-b border-line-2">
        {(['agent', 'supervisor'] as Kind[]).map((k) => (
          <button
            key={k}
            onClick={() => setKind(k)}
            className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium border-b-2 -mb-px transition-colors ${
              kind === k
                ? 'border-accent-400 text-accent-400'
                : 'border-transparent text-gray-200 hover:text-gray-50'
            }`}
            aria-pressed={kind === k}
          >
            {k === 'agent' ? (
              <Bot className="w-3.5 h-3.5" />
            ) : (
              <ServerCog className="w-3.5 h-3.5" />
            )}
            {KIND_LABELS[k]}
          </button>
        ))}
      </div>

      <BinaryReleasePanel kind={kind} />
    </div>
  )
}

interface PanelProps {
  kind: Kind
}

function BinaryReleasePanel({ kind }: PanelProps) {
  const qc = useQueryClient()
  const queryKey = useMemo(() => ['admin-releases', kind], [kind])
  const { data: releases = [], isLoading } = useQuery<Release[]>({
    queryKey,
    queryFn: () => api.get(ENDPOINTS[kind]).then((r) => r.data),
  })

  const del = useMutation({
    mutationFn: (id: string) => api.delete(`${ENDPOINTS[kind]}/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey }),
    onError: () => showErrorToast('リリースの削除に失敗しました'),
  })

  return (
    <div>
      <UploadForm kind={kind} onUploaded={() => qc.invalidateQueries({ queryKey })} />

      <div className="border border-line-2 rounded-very overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-800/60 text-[11px] uppercase tracking-[0.08em] text-gray-200">
            <tr>
              <th className="px-4 py-3 text-left font-medium">バージョン</th>
              <th className="px-4 py-3 text-left font-medium">OS / arch</th>
              <th className="px-4 py-3 text-left font-medium">チャンネル</th>
              <th className="px-4 py-3 text-left font-medium">サイズ</th>
              <th className="px-4 py-3 text-left font-medium">SHA-256</th>
              <th className="px-4 py-3 text-left font-medium">登録</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-line-1 bg-gray-800/30">
            {isLoading ? (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-gray-200">
                  読み込み中...
                </td>
              </tr>
            ) : releases.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-gray-200">
                  リリースがありません — 上のフォームからアップロードしてください
                </td>
              </tr>
            ) : (
              releases.map((r) => (
                <tr key={r.id} className="hover:bg-gray-700/40">
                  <td className="px-4 py-3 font-mono text-gray-50">
                    {r.version}
                  </td>
                  <td className="px-4 py-3 text-gray-50">
                    {r.os_type} / {r.arch}
                  </td>
                  <td className="px-4 py-3 text-gray-50">
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full ${
                        r.channel === 'stable'
                          ? 'bg-status-done/20 text-status-done'
                          : r.channel === 'beta'
                          ? 'bg-status-progress/20 text-status-progress'
                          : 'bg-status-hold/20 text-status-hold'
                      }`}
                    >
                      {r.channel}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-200">
                    {formatSize(r.size_bytes)}
                  </td>
                  <td className="px-4 py-3 font-mono text-[11px] text-gray-200" title={r.sha256}>
                    {r.sha256.slice(0, 12)}…
                  </td>
                  <td className="px-4 py-3 text-gray-200">
                    {new Date(r.created_at).toLocaleDateString('ja-JP')}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => {
                        if (confirm(`v${r.version} (${r.os_type}/${r.channel}/${r.arch}) を削除しますか？`)) {
                          del.mutate(r.id)
                        }
                      }}
                      disabled={del.isPending}
                      className="text-gray-300 hover:text-pri-urgent disabled:opacity-50"
                      aria-label="削除"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

interface UploadFormProps {
  kind: Kind
  onUploaded: () => void
}

function UploadForm({ kind, onUploaded }: UploadFormProps) {
  const [version, setVersion] = useState('')
  const [osType, setOsType] = useState<Release['os_type']>('win32')
  const [arch, setArch] = useState<string>('x64')
  const [channel, setChannel] = useState<Release['channel']>('stable')
  const [releaseNotes, setReleaseNotes] = useState('')
  const [file, setFile] = useState<File | null>(null)

  const upload = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('file required')
      const fd = new FormData()
      fd.append('version', version)
      fd.append('os_type', osType)
      fd.append('arch', arch)
      fd.append('channel', channel)
      fd.append('release_notes', releaseNotes)
      fd.append('file', file)
      return api.post(ENDPOINTS[kind], fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
    },
    onSuccess: () => {
      showSuccessToast(`${KIND_LABELS[kind]} v${version} をアップロードしました`)
      setVersion('')
      setReleaseNotes('')
      setFile(null)
      onUploaded()
    },
    onError: (e: unknown) => {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (e as Error)?.message ??
        'unknown'
      showErrorToast(`アップロード失敗: ${detail}`)
    },
  })

  const canSubmit = !!file && /^\d+(\.\d+)*([\-+].+)?$/.test(version) && !upload.isPending

  return (
    <div className="border border-line-2 rounded-very p-4 mb-4 bg-gray-800/30">
      <h3 className="text-sm font-medium text-gray-50 mb-3 flex items-center gap-1.5">
        <Upload className="w-4 h-4" />
        新しい {KIND_LABELS[kind]} リリースをアップロード
      </h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <label className="flex flex-col gap-1 text-xs text-gray-200">
          バージョン (semver)
          <input
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            placeholder="0.2.0"
            className="border border-line-2 rounded-comfortable px-3 py-2 text-sm bg-gray-900 text-gray-50 placeholder:text-gray-200 focus:outline-none focus:ring-2 focus:ring-focus focus:border-accent-400 font-mono"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-gray-200">
          OS
          <select
            value={osType}
            onChange={(e) => setOsType(e.target.value as Release['os_type'])}
            className="border border-line-2 rounded-comfortable px-3 py-2 text-sm bg-gray-900 text-gray-50 focus:outline-none focus:ring-2 focus:ring-focus focus:border-accent-400"
          >
            {OS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-gray-200">
          アーキテクチャ
          <select
            value={arch}
            onChange={(e) => setArch(e.target.value)}
            className="border border-line-2 rounded-comfortable px-3 py-2 text-sm bg-gray-900 text-gray-50 focus:outline-none focus:ring-2 focus:ring-focus focus:border-accent-400"
          >
            {ARCH_OPTIONS.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-gray-200">
          チャンネル
          <select
            value={channel}
            onChange={(e) => setChannel(e.target.value as Release['channel'])}
            className="border border-line-2 rounded-comfortable px-3 py-2 text-sm bg-gray-900 text-gray-50 focus:outline-none focus:ring-2 focus:ring-focus focus:border-accent-400"
          >
            {CHANNEL_OPTIONS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label className="md:col-span-2 flex flex-col gap-1 text-xs text-gray-200">
          バイナリファイル
          <input
            type="file"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="border border-line-2 rounded-comfortable px-3 py-2 text-sm bg-gray-900 text-gray-50 focus:outline-none focus:ring-2 focus:ring-focus focus:border-accent-400"
          />
          {file && (
            <span className="text-[11px] text-gray-200">
              {file.name} ({formatSize(file.size)})
            </span>
          )}
        </label>
        <label className="md:col-span-2 flex flex-col gap-1 text-xs text-gray-200">
          リリースノート (optional)
          <textarea
            value={releaseNotes}
            onChange={(e) => setReleaseNotes(e.target.value)}
            rows={2}
            className="border border-line-2 rounded-comfortable px-3 py-2 text-sm bg-gray-900 text-gray-50 placeholder:text-gray-200 focus:outline-none focus:ring-2 focus:ring-focus focus:border-accent-400 resize-y"
            placeholder="変更点 / 既知の問題など"
          />
        </label>
      </div>
      <div className="mt-3 flex justify-end">
        <button
          onClick={() => upload.mutate()}
          disabled={!canSubmit}
          className="flex items-center gap-1.5 px-4 py-2 text-sm bg-accent-500 text-gray-50 rounded-comfortable hover:bg-accent-400 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Upload className="w-4 h-4" />
          {upload.isPending ? 'アップロード中...' : 'アップロード'}
        </button>
      </div>
    </div>
  )
}
