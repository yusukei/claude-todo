import { useEffect, useRef, useImperativeHandle, forwardRef } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'

export interface TerminalHandle {
  /** Write data to the terminal display */
  write: (data: string) => void
  /** Get current terminal dimensions */
  getDimensions: () => { cols: number; rows: number }
}

interface TerminalViewProps {
  /** Called when user types in the terminal */
  onInput: (data: string) => void
  /** Called when terminal is resized */
  onResize: (cols: number, rows: number) => void
}

export default forwardRef<TerminalHandle, TerminalViewProps>(
  function TerminalView({ onInput, onResize }, ref) {
    const termRef = useRef<HTMLDivElement>(null)
    const terminalRef = useRef<Terminal | null>(null)
    const fitAddonRef = useRef<FitAddon | null>(null)
    const cbRef = useRef({ onInput, onResize })
    cbRef.current = { onInput, onResize }

    useImperativeHandle(ref, () => ({
      write: (data: string) => terminalRef.current?.write(data),
      getDimensions: () => ({
        cols: terminalRef.current?.cols ?? 120,
        rows: terminalRef.current?.rows ?? 40,
      }),
    }))

    useEffect(() => {
      if (!termRef.current) return

      const terminal = new Terminal({
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
      terminal.open(termRef.current)
      fitAddon.fit()

      terminalRef.current = terminal
      fitAddonRef.current = fitAddon

      terminal.onData((data) => cbRef.current.onInput(data))

      const resizeObserver = new ResizeObserver(() => {
        fitAddon.fit()
        cbRef.current.onResize(terminal.cols, terminal.rows)
      })
      resizeObserver.observe(termRef.current)

      // Report initial dimensions
      cbRef.current.onResize(terminal.cols, terminal.rows)

      return () => {
        resizeObserver.disconnect()
        terminal.dispose()
        terminalRef.current = null
        fitAddonRef.current = null
      }
    }, [])

    return <div ref={termRef} className="h-full bg-[#1a1b26]" />
  }
)
