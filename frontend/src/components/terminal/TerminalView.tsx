import { useEffect, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { api } from '../../api/client'

interface TerminalViewProps {
  agentId: string
  agentName: string
  shell?: string
  joinSessionId?: string
  onSessionStarted?: (sessionId: string) => void
  onDisconnect?: (reason: string) => void
  onViewersChanged?: (viewers: number) => void
}

export default function TerminalView({
  agentId, agentName, shell, joinSessionId,
  onSessionStarted, onDisconnect, onViewersChanged,
}: TerminalViewProps) {
  const termRef = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<'connecting' | 'connected' | 'disconnected'>('connecting')

  // Stable refs for callbacks — avoid re-triggering connection
  const cbRef = useRef({ onSessionStarted, onDisconnect, onViewersChanged })
  cbRef.current = { onSessionStarted, onDisconnect, onViewersChanged }

  useEffect(() => {
    if (!termRef.current) return

    let ws: WebSocket | null = null
    let terminal: Terminal | null = null
    let resizeObserver: ResizeObserver | null = null
    let cancelled = false

    ;(async () => {
      // Get ticket
      let ticket: string
      try {
        const res = await api.post('/terminal/ticket')
        ticket = res.data.ticket
      } catch {
        if (!cancelled) {
          setStatus('disconnected')
          cbRef.current.onDisconnect?.('Failed to get ticket')
        }
        return
      }
      if (cancelled) return

      // Init terminal
      terminal = new Terminal({
        cursorBlink: true,
        fontSize: 14,
        fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', Menlo, Monaco, 'Courier New', monospace",
        theme: {
          background: '#1a1b26',
          foreground: '#a9b1d6',
          cursor: '#c0caf5',
          selectionBackground: '#33467c',
          black: '#32344a',
          red: '#f7768e',
          green: '#9ece6a',
          yellow: '#e0af68',
          blue: '#7aa2f7',
          magenta: '#ad8ee6',
          cyan: '#449dab',
          white: '#787c99',
          brightBlack: '#444b6a',
          brightRed: '#ff7a93',
          brightGreen: '#b9f27c',
          brightYellow: '#ff9e64',
          brightBlue: '#7da6ff',
          brightMagenta: '#bb9af7',
          brightCyan: '#0db9d7',
          brightWhite: '#acb0d0',
        },
      })
      const fitAddon = new FitAddon()
      terminal.loadAddon(fitAddon)
      terminal.open(termRef.current!)
      fitAddon.fit()

      terminal.writeln(`\x1b[36m${joinSessionId ? 'Joining' : 'Connecting to'} ${agentName}...\x1b[0m`)

      // WebSocket
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const params = new URLSearchParams({ ticket, agent_id: agentId })
      if (shell) params.set('shell', shell)
      if (joinSessionId) params.set('session_id', joinSessionId)

      ws = new WebSocket(`${proto}//${window.location.host}/api/v1/terminal/session/ws?${params}`)

      const t = terminal  // capture for closures

      ws.onopen = () => {
        setStatus('connected')
        t.writeln(`\x1b[32mConnected.\x1b[0m\r\n`)
      }

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === 'output') {
            t.write(msg.data)
          } else if (msg.type === 'session_started') {
            cbRef.current.onSessionStarted?.(msg.session_id)
          } else if (msg.type === 'session_joined') {
            cbRef.current.onSessionStarted?.(msg.session_id)
            cbRef.current.onViewersChanged?.(msg.viewers)
          } else if (msg.type === 'viewer_changed') {
            cbRef.current.onViewersChanged?.(msg.viewers)
          } else if (msg.type === 'session_ended') {
            t.writeln(`\r\n\x1b[33mSession ended: ${msg.reason || 'unknown'}\x1b[0m`)
            setStatus('disconnected')
            cbRef.current.onDisconnect?.(msg.reason || 'session_ended')
          } else if (msg.type === 'error') {
            t.writeln(`\r\n\x1b[31mError: ${msg.message}\x1b[0m`)
          }
        } catch { /* ignore */ }
      }

      ws.onclose = (event) => {
        t.writeln(`\r\n\x1b[33mConnection closed (${event.code})\x1b[0m`)
        setStatus('disconnected')
        cbRef.current.onDisconnect?.(event.reason || `closed:${event.code}`)
      }

      ws.onerror = () => {
        t.writeln(`\r\n\x1b[31mWebSocket error\x1b[0m`)
      }

      const wsCapture = ws
      t.onData((data) => {
        if (wsCapture.readyState === WebSocket.OPEN) {
          wsCapture.send(JSON.stringify({ type: 'input', data }))
        }
      })

      // Resize
      resizeObserver = new ResizeObserver(() => {
        fitAddon.fit()
        if (wsCapture.readyState === WebSocket.OPEN) {
          wsCapture.send(JSON.stringify({
            type: 'resize',
            cols: t.cols,
            rows: t.rows,
          }))
        }
      })
      resizeObserver.observe(termRef.current!)
    })()

    return () => {
      cancelled = true
      resizeObserver?.disconnect()
      ws?.close()
      terminal?.dispose()
    }
    // Only reconnect when identity changes, NOT when callbacks change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId, agentName, shell, joinSessionId])

  return (
    <div className="flex flex-col h-full">
      <div ref={termRef} className="flex-1 bg-[#1a1b26]" />
    </div>
  )
}
