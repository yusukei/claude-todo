import type { Terminal, IDisposable } from '@xterm/xterm'

/**
 * PredictiveEngine — local-echo speculation for the Web Terminal.
 *
 * On printable ASCII input we paint a dim+underscore character at the
 * cursor immediately, save/restore the cursor so the server's echo
 * overwrites the predicted cell exactly, and reconcile a FIFO queue
 * when the real byte arrives.
 *
 * Suppressed when:
 *   - alt-screen is active (vim/htop/less/man/tmux)
 *   - DECCKM (cursor-keys application mode) or mouse tracking is on
 *   - bracketed paste is in progress (xterm CSI ?2004h)
 *   - the cursor sits within one column of the line end (autowrap is
 *     terminal-specific and we cannot guarantee position)
 *   - the server emitted any ESC sequence in the last 200 ms (a redraw
 *     may be coming, and we should not race it)
 *   - the user disabled predictions via the kill switch
 */

const PREDICT_TIMEOUT_MS = 500
const PENDING_LIMIT = 32
const ESC_QUIET_MS = 200

interface PredictedChar {
  ch: string
  insertedAt: number
}

export interface PredictionMetrics {
  predicted: number
  confirmed: number
  rolledBack: number
}

export interface PredictiveEngineOptions {
  terminal: Terminal
  onSend: (data: string) => void
  onMetrics?: (m: PredictionMetrics) => void
}

export class PredictiveEngine {
  private terminal: Terminal
  private onSend: (data: string) => void
  private onMetrics?: (m: PredictionMetrics) => void
  private killSwitchOff = false
  private pending: PredictedChar[] = []
  private metrics: PredictionMetrics = {
    predicted: 0,
    confirmed: 0,
    rolledBack: 0,
  }
  private lastEscFromServer = 0
  private altScreen = false
  private cursorKeysApp = false
  private mouseTracking = false
  private bracketedPaste = false
  private timeoutTimer: ReturnType<typeof setTimeout> | null = null
  private disposers: IDisposable[] = []

  constructor(opts: PredictiveEngineOptions) {
    this.terminal = opts.terminal
    this.onSend = opts.onSend
    this.onMetrics = opts.onMetrics
    this.installCsiHandlers()
  }

  /** Forward keyboard input to the server, optionally painting predictions. */
  onUserInput(data: string): void {
    this.onSend(data)
    if (!this.canPredict()) return

    const cols = this.terminal.cols
    const cursorX = this.terminal.buffer.active.cursorX
    const remaining = cols - cursorX - 1
    if (remaining <= 0) return

    const candidates: PredictedChar[] = []
    const now = performance.now()
    for (const ch of data) {
      const code = ch.charCodeAt(0)
      if (code < 0x20 || code > 0x7e) break // first non-printable byte stops the run
      if (this.pending.length + candidates.length >= PENDING_LIMIT) break
      if (candidates.length >= remaining) break
      candidates.push({ ch, insertedAt: now })
    }
    if (candidates.length === 0) return

    const text = candidates.map((c) => c.ch).join('')
    // Save cursor → write predicted text in the terminal's normal SGR
    // → restore cursor. Originally we shipped the prediction in
    // dim+underscore so users could spot mispredictions, but the
    // visual difference reads as "stuttering" even when the prediction
    // is correct, defeating the whole point of speculation. Mismatches
    // are still self-correcting because the server echo for the wrong
    // byte overwrites the predicted cell with the canonical character.
    this.terminal.write(`\x1b[s${text}\x1b[u`)
    this.pending.push(...candidates)
    this.metrics.predicted += candidates.length
    this.scheduleTimeout()
    this.emitMetrics()
  }

  /**
   * Inspect a server output frame for matches against predicted chars.
   *
   * Must be called BEFORE ``terminal.write(data)`` so we can advance
   * the FIFO and clear the pending queue in lockstep with the visible
   * frame xterm.js is about to render.
   */
  onServerData(data: string): void {
    this.gcStale()

    let i = 0
    while (i < data.length) {
      const code = data.charCodeAt(i)
      if (code === 0x1b) {
        this.lastEscFromServer = performance.now()
        // Skip the rest of any escape sequence; CSI handlers update
        // altScreen/cursorKeysApp/mouseTracking when xterm.js parses
        // the same bytes via terminal.write below.
        i = this.skipEscapeSequence(data, i)
        continue
      }
      if (code >= 0x20 && code <= 0x7e) {
        const head = this.pending[0]
        if (head && head.ch === data[i]) {
          this.pending.shift()
          this.metrics.confirmed += 1
        }
      }
      // Other control bytes (CR/LF/Tab/BS/...) do not match predicted
      // characters; the stale GC drops orphaned predictions later.
      i += 1
    }

    if (this.pending.length === 0 && this.timeoutTimer != null) {
      clearTimeout(this.timeoutTimer)
      this.timeoutTimer = null
    }
    if (this.metrics.predicted > 0) this.emitMetrics()
  }

  toggleKillSwitch(): boolean {
    this.killSwitchOff = !this.killSwitchOff
    if (this.killSwitchOff) this.rollbackAll()
    return this.killSwitchOff
  }

  setKillSwitch(off: boolean): void {
    if (this.killSwitchOff === off) return
    this.killSwitchOff = off
    if (off) this.rollbackAll()
  }

  isKillSwitchOff(): boolean {
    return this.killSwitchOff
  }

  isActive(): boolean {
    return !this.killSwitchOff && !this.altScreen
  }

  onDisconnect(): void {
    this.rollbackAll()
  }

  getMetrics(): PredictionMetrics {
    return { ...this.metrics }
  }

  dispose(): void {
    if (this.timeoutTimer != null) {
      clearTimeout(this.timeoutTimer)
      this.timeoutTimer = null
    }
    for (const d of this.disposers) {
      try { d.dispose() } catch { /* ignore disposer errors */ }
    }
    this.disposers = []
  }

  // ── Internals ──────────────────────────────────────────────

  private canPredict(): boolean {
    if (this.killSwitchOff) return false
    if (this.altScreen) return false
    if (this.cursorKeysApp) return false
    if (this.mouseTracking) return false
    if (this.bracketedPaste) return false
    if (performance.now() - this.lastEscFromServer < ESC_QUIET_MS) return false
    return true
  }

  private rollbackAll(): void {
    if (this.pending.length === 0) return
    this.metrics.rolledBack += this.pending.length
    this.pending.length = 0
    this.emitMetrics()
  }

  private gcStale(): void {
    const now = performance.now()
    let dropped = 0
    while (
      this.pending.length > 0 &&
      now - this.pending[0].insertedAt > PREDICT_TIMEOUT_MS
    ) {
      this.pending.shift()
      dropped += 1
    }
    if (dropped > 0) {
      this.metrics.rolledBack += dropped
      this.emitMetrics()
    }
  }

  private scheduleTimeout(): void {
    if (this.timeoutTimer != null) return
    this.timeoutTimer = setTimeout(() => {
      this.timeoutTimer = null
      this.gcStale()
    }, PREDICT_TIMEOUT_MS + 50)
  }

  private skipEscapeSequence(data: string, i: number): number {
    // Cheap walker: ESC is at i; consume up to and including the
    // sequence's final byte. Covers CSI / OSC / SS3 in the common
    // forms emitted by bash and TUIs. Anything fancier we just
    // bail on after a few bytes — the next byte will be re-examined.
    if (i + 1 >= data.length) return i + 1
    const next = data[i + 1]
    if (next === '[') {
      // CSI: ESC [ params final, where final is 0x40-0x7e
      let j = i + 2
      while (j < data.length) {
        const c = data.charCodeAt(j)
        if (c >= 0x40 && c <= 0x7e) return j + 1
        j += 1
      }
      return j
    }
    if (next === ']') {
      // OSC: ESC ] params (BEL | ESC \\)
      let j = i + 2
      while (j < data.length) {
        if (data.charCodeAt(j) === 0x07) return j + 1
        if (data[j] === '\\' && j > 0 && data.charCodeAt(j - 1) === 0x1b) return j + 1
        j += 1
      }
      return j
    }
    // ESC X (single intermediate) or 2-byte sequence
    return i + 2
  }

  private emitMetrics(): void {
    if (this.onMetrics) this.onMetrics({ ...this.metrics })
  }

  private installCsiHandlers(): void {
    // ``?2004h/l`` is *paste-aware mode* (bash readline always sets it
    // at every prompt), not a paste boundary — suppressing predictions
    // while it is on stops them for the entire session. The real paste
    // boundary is ``CSI 200~`` (start) / ``CSI 201~`` (end), handled
    // in a separate ``final: '~'`` registration below.
    this.disposers.push(
      this.terminal.parser.registerCsiHandler({ prefix: '?', final: 'h' }, (params) => {
        for (const p of params) {
          const v = Array.isArray(p) ? p[0] : p
          if (v === 1049 || v === 47 || v === 1047 || v === 1048) {
            this.altScreen = true
            this.rollbackAll()
          } else if (v === 1) {
            this.cursorKeysApp = true
          } else if (v === 1000 || v === 1006 || v === 1015) {
            this.mouseTracking = true
          }
        }
        return false
      }),
    )
    this.disposers.push(
      this.terminal.parser.registerCsiHandler({ prefix: '?', final: 'l' }, (params) => {
        for (const p of params) {
          const v = Array.isArray(p) ? p[0] : p
          if (v === 1049 || v === 47 || v === 1047 || v === 1048) {
            this.altScreen = false
          } else if (v === 1) {
            this.cursorKeysApp = false
          } else if (v === 1000 || v === 1006 || v === 1015) {
            this.mouseTracking = false
          }
        }
        return false
      }),
    )
    // Real paste boundary: CSI 200~ (start) / CSI 201~ (end).
    this.disposers.push(
      this.terminal.parser.registerCsiHandler({ final: '~' }, (params) => {
        for (const p of params) {
          const v = Array.isArray(p) ? p[0] : p
          if (v === 200) {
            this.bracketedPaste = true
            this.rollbackAll()
          } else if (v === 201) {
            this.bracketedPaste = false
          }
        }
        return false
      }),
    )
  }
}
