import { useState, useCallback, useEffect, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, TerminalSquare, RefreshCw, X, Users } from 'lucide-react'
import { api } from '../api/client'
import AgentList, { type Agent } from '../components/terminal/AgentList'
import AgentRegisterDialog from '../components/terminal/AgentRegisterDialog'
import TerminalView, { type TerminalHandle } from '../components/terminal/TerminalView'

interface SessionInfo {
  session_id: string
  agent_id: string
  shell: string
  started_at: string
  viewers: number
}

export default function TerminalPage() {
  const qc = useQueryClient()
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null)
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const [showRegister, setShowRegister] = useState(false)
  const [wsStatus, setWsStatus] = useState<'disconnected' | 'connecting' | 'connected'>('disconnected')

  const wsRef = useRef<WebSocket | null>(null)
  const terminalRefs = useRef<Map<string, TerminalHandle>>(new Map())

  const { data: agents = [], isLoading } = useQuery({
    queryKey: ['terminal-agents'],
    queryFn: () => api.get('/terminal/agents').then((r) => r.data),
    refetchInterval: 5000,
  })

  const deleteMutation = useMutation({
    mutationFn: (agentId: string) => api.delete(`/terminal/agents/${agentId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['terminal-agents'] }),
  })

  // ── Fetch session list from server ──────────────────────
  const fetchSessions = useCallback(async (agentId: string) => {
    try {
      const res = await api.get('/terminal/sessions', { params: { agent_id: agentId } })
      setSessions(res.data)
    } catch {
      setSessions([])
    }
  }, [])

  // ── WebSocket management ────────────────────────────────
  const connectWs = useCallback(async (agentId: string) => {
    // Close existing
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    setWsStatus('connecting')

    let ticket: string
    try {
      const res = await api.post('/terminal/ticket')
      ticket = res.data.ticket
    } catch {
      setWsStatus('disconnected')
      return
    }

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const params = new URLSearchParams({ ticket, agent_id: agentId })
    const ws = new WebSocket(`${proto}//${window.location.host}/api/v1/terminal/ws?${params}`)
    wsRef.current = ws

    ws.onopen = () => setWsStatus('connected')

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        switch (msg.type) {
          case 'session_list':
            setSessions(msg.sessions)
            break
          case 'output': {
            const handle = terminalRefs.current.get(msg.session_id)
            handle?.write(msg.data)
            break
          }
          case 'session_started':
            setActiveSessionId(msg.session_id)
            fetchSessions(agentId)
            break
          case 'session_joined':
            // Already viewing — just update viewer count
            fetchSessions(agentId)
            break
          case 'sessions_changed':
            fetchSessions(agentId)
            break
          case 'session_ended':
            fetchSessions(agentId)
            if (activeSessionId === msg.session_id) {
              // Write end message to terminal
              const handle = terminalRefs.current.get(msg.session_id)
              handle?.write(`\r\n\x1b[33mSession ended: ${msg.reason || 'unknown'}\x1b[0m`)
            }
            break
          case 'viewer_changed':
            setSessions((prev) =>
              prev.map((s) => s.session_id === msg.session_id ? { ...s, viewers: msg.viewers } : s)
            )
            break
          case 'error':
            console.error('Terminal error:', msg.message)
            break
        }
      } catch { /* ignore */ }
    }

    ws.onclose = () => setWsStatus('disconnected')
    ws.onerror = () => setWsStatus('disconnected')
  }, [fetchSessions, activeSessionId])

  // ── Agent selection ─────────────────────────────────────
  const handleSelectAgent = useCallback((agent: Agent) => {
    if (selectedAgent?.id === agent.id) return
    setSelectedAgent(agent)
    setActiveSessionId(null)
    setSessions([])
    terminalRefs.current.clear()
    connectWs(agent.id)
  }, [selectedAgent, connectWs])

  // ── Session commands (sent via WS) ──────────────────────
  const sendWs = useCallback((msg: object) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg))
    }
  }, [])

  const handleCreateSession = useCallback(() => {
    if (!selectedAgent) return
    const shell = selectedAgent.available_shells[0] || ''
    // Get dimensions from active terminal if available
    const dims = activeSessionId
      ? terminalRefs.current.get(activeSessionId)?.getDimensions()
      : undefined
    sendWs({
      type: 'session_create',
      shell,
      cols: dims?.cols ?? 120,
      rows: dims?.rows ?? 40,
    })
  }, [selectedAgent, activeSessionId, sendWs])

  const handleCloseSession = useCallback((sessionId: string) => {
    sendWs({ type: 'session_close', session_id: sessionId })
  }, [sendWs])

  const handleJoinSession = useCallback((sessionId: string) => {
    sendWs({ type: 'session_join', session_id: sessionId })
    setActiveSessionId(sessionId)
  }, [sendWs])

  const handleLeaveSession = useCallback((sessionId: string) => {
    sendWs({ type: 'session_leave', session_id: sessionId })
  }, [sendWs])

  // ── Tab switch: join new, leave old ─────────────────────
  const handleTabSwitch = useCallback((sessionId: string) => {
    if (activeSessionId && activeSessionId !== sessionId) {
      handleLeaveSession(activeSessionId)
    }
    handleJoinSession(sessionId)
  }, [activeSessionId, handleJoinSession, handleLeaveSession])

  // ── Terminal input/resize → WS ──────────────────────────
  const handleInput = useCallback((data: string) => {
    if (!activeSessionId) return
    sendWs({ type: 'input', session_id: activeSessionId, data })
  }, [activeSessionId, sendWs])

  const handleResize = useCallback((cols: number, rows: number) => {
    if (!activeSessionId) return
    sendWs({ type: 'resize', session_id: activeSessionId, cols, rows })
  }, [activeSessionId, sendWs])

  // ── Cleanup on unmount ──────────────────────────────────
  useEffect(() => {
    return () => {
      wsRef.current?.close()
    }
  }, [])

  const handleDeleteAgent = useCallback((agentId: string) => {
    if (confirm('この Agent を削除しますか？')) {
      deleteMutation.mutate(agentId)
      if (selectedAgent?.id === agentId) {
        setSelectedAgent(null)
        setSessions([])
        setActiveSessionId(null)
      }
    }
  }, [deleteMutation, selectedAgent])

  // Auto-join first session on connect if available
  useEffect(() => {
    if (sessions.length > 0 && !activeSessionId && wsStatus === 'connected') {
      handleJoinSession(sessions[0].session_id)
    }
  }, [sessions, activeSessionId, wsStatus, handleJoinSession])

  return (
    <div className="flex h-full overflow-hidden">
      {/* Sidebar */}
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
              selectedAgentId={selectedAgent?.id ?? null}
              onSelect={handleSelectAgent}
              onDelete={handleDeleteAgent}
            />
          )}
        </div>
      </div>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Session tabs */}
        {selectedAgent && (
          <div className="flex items-center bg-gray-900 border-b border-gray-700">
            <div className="flex-1 flex items-center overflow-x-auto">
              {sessions.map((s) => (
                <div
                  key={s.session_id}
                  className={`group flex items-center gap-1.5 px-3 py-1.5 text-xs cursor-pointer border-r border-gray-700 min-w-0 ${
                    s.session_id === activeSessionId
                      ? 'bg-[#1a1b26] text-gray-200'
                      : 'bg-gray-800 text-gray-500 hover:text-gray-300'
                  }`}
                  onClick={() => handleTabSwitch(s.session_id)}
                >
                  <span className="truncate max-w-[120px]">{s.shell.split(/[/\\]/).pop() || 'shell'}</span>
                  <span className="text-gray-600 flex-shrink-0">#{s.session_id.slice(0, 6)}</span>
                  {s.viewers > 0 && (
                    <span className="flex items-center gap-0.5 text-green-500 flex-shrink-0" title={`${s.viewers} viewers`}>
                      <Users className="w-3 h-3" />
                      {s.viewers}
                    </span>
                  )}
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      handleCloseSession(s.session_id)
                    }}
                    className="flex-shrink-0 p-0.5 rounded text-gray-600 hover:text-red-400 opacity-0 group-hover:opacity-100"
                    title="セッション終了"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
            <button
              onClick={handleCreateSession}
              disabled={!selectedAgent.is_online || wsStatus !== 'connected'}
              className="flex-shrink-0 px-2 py-1.5 text-gray-400 hover:text-gray-200 disabled:opacity-30"
              title="新規セッション"
            >
              <Plus className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Terminal */}
        {activeSessionId ? (
          <div className="flex-1 min-h-0">
            <TerminalView
              key={activeSessionId}
              ref={(handle) => {
                if (handle) {
                  terminalRefs.current.set(activeSessionId, handle)
                } else {
                  terminalRefs.current.delete(activeSessionId)
                }
              }}
              onInput={handleInput}
              onResize={handleResize}
            />
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center bg-gray-50 dark:bg-gray-900">
            <div className="text-center text-gray-400 dark:text-gray-500">
              <TerminalSquare className="w-12 h-12 mx-auto mb-3 opacity-30" />
              <p className="text-sm">
                {!selectedAgent
                  ? 'Agent を選択してください'
                  : sessions.length === 0
                    ? '「+」をクリックして新しいセッションを開始'
                    : 'セッションタブをクリックして接続'}
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
