import { useState, useRef } from 'react'
import { Download, Upload, AlertTriangle } from 'lucide-react'
import { api } from '../../api/client'
import { showErrorToast, showSuccessToast } from '../../components/common/Toast'

export default function BackupRestoreTab() {
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [confirmRestore, setConfirmRestore] = useState<File | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const handleExport = async () => {
    setExporting(true)
    try {
      const res = await api.post('/backup/export', null, { responseType: 'blob' })
      const url = window.URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      const disposition = res.headers.get('content-disposition')
      const filename = disposition
        ? disposition.split('filename=')[1]?.replace(/"/g, '')
        : `backup_${new Date().toISOString().slice(0, 19).replace(/[:-]/g, '')}.zip`
      a.download = filename
      a.click()
      window.URL.revokeObjectURL(url)
    } catch {
      showErrorToast('バックアップの作成に失敗しました')
    } finally {
      setExporting(false)
    }
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      setConfirmRestore(file)
    }
    e.target.value = ''
  }

  const handleRestore = async () => {
    if (!confirmRestore) return
    setImporting(true)
    setConfirmRestore(null)
    try {
      const formData = new FormData()
      formData.append('file', confirmRestore)
      await api.post('/backup/import', formData)
      showSuccessToast('リストアが完了しました。ページを再読み込みします。')
      window.location.reload()
    } catch {
      showErrorToast('リストアに失敗しました')
    } finally {
      setImporting(false)
    }
  }

  return (
    <div>
      <h2 className="font-serif text-base font-semibold text-gray-50 mb-4">バックアップ / リストア</h2>

      {/* Backup Section */}
      <div className="mb-6 p-4 border border-line-2 rounded-very">
        <h3 className="text-sm font-semibold text-gray-50 mb-1">バックアップ</h3>
        <p className="text-xs text-gray-200 mb-3">
          データベースとアセットファイル（DocSite・ブックマーク）を .zip 形式でダウンロードします。
        </p>
        <button
          onClick={handleExport}
          disabled={exporting}
          className="flex items-center gap-1.5 px-3 py-2 text-sm bg-accent-500 text-gray-50 rounded-comfortable hover:bg-accent-400 disabled:opacity-50"
        >
          <Download className="w-4 h-4" />
          {exporting ? 'バックアップ中...' : 'バックアップ作成'}
        </button>
      </div>

      {/* Restore Section */}
      <div className="p-4 border border-line-2 rounded-very">
        <h3 className="text-sm font-semibold text-gray-50 mb-1">リストア</h3>
        <p className="text-xs text-gray-200 mb-3">
          バックアップファイル（.zip）からデータベースとアセットを復元します。既存のデータは上書きされます。
          旧形式（.agz）のインポートにも対応しています。
        </p>
        <label className="inline-flex items-center gap-1.5 px-3 py-2 text-sm bg-status-hold text-gray-50 rounded-comfortable hover:bg-status-hold/80 cursor-pointer">
          <Upload className="w-4 h-4" />
          {importing ? 'リストア中...' : 'ファイルを選択してリストア'}
          <input
            ref={fileRef}
            type="file"
            accept=".zip,.agz"
            onChange={handleFileSelect}
            disabled={importing}
            className="hidden"
          />
        </label>
      </div>

      {/* Confirmation Modal */}
      {confirmRestore && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-very p-6 max-w-md mx-4 shadow-xl border border-line-2">
            <div className="flex items-center gap-3 mb-4">
              <AlertTriangle className="w-6 h-6 text-status-hold" />
              <h3 className="font-serif text-base font-semibold text-gray-50">リストアの確認</h3>
            </div>
            <p className="text-sm text-gray-200 mb-2">
              ファイル: <span className="font-mono text-xs text-gray-50">{confirmRestore.name}</span>
            </p>
            <p className="text-sm text-pri-urgent mb-6">
              全てのデータが上書きされます。この操作は取り消せません。
            </p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setConfirmRestore(null)}
                className="px-4 py-2 text-sm border border-line-2 text-gray-100 hover:bg-gray-700 rounded-comfortable transition-colors"
              >
                キャンセル
              </button>
              <button
                onClick={handleRestore}
                className="px-4 py-2 text-sm bg-pri-urgent text-gray-50 rounded-comfortable hover:bg-pri-urgent/80 transition-colors"
              >
                リストア実行
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
