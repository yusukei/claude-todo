import { useState, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, TerminalSquare, RefreshCw, X, Users, MonitorUp } from 'lucide-react'
import { api } from '../api/client'
import AgentList, { type Agent } from '../components/terminal/AgentList'
import AgentRegisterDialog from '../components/terminal/AgentRegisterDialog'
import TerminalView from '../components/terminal/TerminalView'

interface SessionTab {
  id: string              // unique tab key
  agentId: string
  agentName: string
  shell: string
  sessionId?: string      // set after session_started
  joinSessionId?: string  // set when joining existing
  viewers: number
}

export default function TerminalPage() {
  const qc = useQueryClient()
  const [tabs, setTabs] = useState<SessionTab[]>([])
  const [activeTabId, setActiveTabId] = useState<string | null>(null)
  const [showRegister, setShowRegister] = useState(false)

  const { data: agents = [], isLoading } = useQuery({
    queryKey: ['terminal-agents'],
    queryFn: () => api.get('/terminal/agents').then((r) => r.data),
    refetchInterval: 5000,
  })

  const deleteMutation = useMutation({
    mutationFn: (agentId: string) => api.delete(`/terminal/agents/${agentId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['terminal-agents'] }),
  })

  // ── New session ──────────────────────────────────────────
  const handleNewSession = useCallback((agent: Agent) => {
    const tabId = crypto.randomUUID().slice(0, 8)
    const tab: SessionTab = {
      id: tabId,
      agentId: agent.id,
      agentName: agent.name,
      shell: agent.available_shells[0] || '',
      viewers: 1,
    }
    setTabs((prev) => [...prev, tab])
    setActiveTabId(tabId)
  }, [])

  // ── Join existing session ────────────────────────────────
  const handleJoinSession = useCallback((agent: Agent, sessionId: string) => {
    const tabId = crypto.randomUUID().slice(0, 8)
    const tab: SessionTab = {
      id: tabId,
      agentId: agent.id,
      agentName: agent.name,
      shell: '',
      joinSessionId: sessionId,
      viewers: 1,
    }
    setTabs((prev) => [...prev, tab])
    setActiveTabId(tabId)
  }, [])

  // ── Close tab ────────────────────────────────────────────
  const handleCloseTab = useCallback((tabId: string) => {
    setTabs((prev) => {
      const next = prev.filter((t) => t.id !== tabId)
      if (activeTabId === tabId) {
        setActiveTabId(next.length > 0 ? next[next.length - 1].id : null)
      }
      return next
    })
  }, [activeTabId])

  const handleSessionStarted = useCallback((tabId: string, sessionId: string) => {
    setTabs((prev) =>
      prev.map((t) => (t.id === tabId ? { ...t, sessionId } : t))
    )
  }, [])

  const handleViewersChanged = useCallback((tabId: string, viewers: number) => {
    setTabs((prev) =>
      prev.map((t) => (t.id === tabId ? { ...t, viewers } : t))
    )
  }, [])

  const handleDisconnect = useCallback((tabId: string) => {
    // Keep tab visible so user can see the disconnect message
  }, [])

  const handleDeleteAgent = useCallback((agentId: string) => {
    if (confirm('この Agent を削除しますか？')) {
      deleteMutation.mutate(agentId)
    }
  }, [deleteMutation])

  const activeTab = tabs.find((t) => t.id === activeTabId) ?? null

  return (
    <div className="flex h-full overflow-hidden">
      {/* Sidebar: Agent list */}
      <div className="w-64 flex-shrink-0 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-700">
          <div className="flex items-center gap-2">
            <TerminalSquare className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
            <h2 className="font-semibold text-sm text-gray-800 dark:text-gray-100">Agents</h2>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => qc.invalidateQueries({ queryKey: ['terminal-agents'] })}
              className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700"
              title="更新"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => setShowRegister(true)}
              className="p-1.5 rounded-lg text-indigo-600 dark:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/30"
              title="Agent 登録"
            >
              <Plus className="w-4 h-4" />
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {isLoading ? (
            <div className="text-center py-8 text-gray-400 text-sm">読み込み中...</div>
          ) : (
            <AgentList
              agents={agents}
              selectedAgentId={activeTab?.agentId ?? null}
              onSelect={handleNewSession}
              onDelete={handleDeleteAgent}
            />
          )}
        </div>
      </div>

      {/* Main area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Session tabs */}
        {tabs.length > 0 && (
          <div className="flex items-center bg-gray-900 border-b border-gray-700 overflow-x-auto">
            {tabs.map((tab) => (
              <div
                key={tab.id}
                className={`group flex items-center gap-1.5 px-3 py-1.5 text-xs cursor-pointer border-r border-gray-700 min-w-0 ${
                  tab.id === activeTabId
                    ? 'bg-[#1a1b26] text-gray-200'
                    : 'bg-gray-800 text-gray-500 hover:text-gray-300 hover:bg-gray-750'
                }`}
                onClick={() => setActiveTabId(tab.id)}
              >
                <span className="truncate max-w-[120px]">{tab.agentName}</span>
                {tab.sessionId && (
                  <span className="text-gray-600 flex-shrink-0">
                    #{tab.sessionId.slice(0, 6)}
                  </span>
                )}
                {tab.viewers > 1 && (
                  <span className="flex items-center gap-0.5 text-green-500 flex-shrink-0" title={`${tab.viewers} viewers`}>
                    <Users className="w-3 h-3" />
                    {tab.viewers}
                  </span>
                )}
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    handleCloseTab(tab.id)
                  }}
                  className="flex-shrink-0 p-0.5 rounded text-gray-600 hover:text-gray-300 opacity-0 group-hover:opacity-100"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Terminal or empty state */}
        {activeTab ? (
          <TerminalView
            key={activeTab.id}
            agentId={activeTab.agentId}
            agentName={activeTab.agentName}
            shell={activeTab.shell}
            joinSessionId={activeTab.joinSessionId}
            onSessionStarted={(sid) => handleSessionStarted(activeTab.id, sid)}
            onViewersChanged={(v) => handleViewersChanged(activeTab.id, v)}
            onDisconnect={() => handleDisconnect(activeTab.id)}
          />
        ) : (
          <div className="flex-1 flex items-center justify-center bg-gray-50 dark:bg-gray-900">
            <div className="text-center text-gray-400 dark:text-gray-500">
              <TerminalSquare className="w-12 h-12 mx-auto mb-3 opacity-30" />
              <p className="text-sm">
                {agents.length === 0
                  ? 'Agent を登録してリモートターミナルに接続'
                  : 'オンラインの Agent をクリックして新しいセッションを開始'}
              </p>
            </div>
          </div>
        )}
      </div>

      <AgentRegisterDialog
        open={showRegister}
        onClose={() => setShowRegister(false)}
        onCreated={() => qc.invalidateQueries({ queryKey: ['terminal-agents'] })}
      />
    </div>
  )
}
