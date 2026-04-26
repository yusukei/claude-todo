import type { Task, TaskPriority } from '../types'

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR
const WEEK = 7 * DAY

export type TimelineUnit = 'minute' | 'hour' | 'day' | 'week' | 'month'

export interface TimelineScale {
  tMin: number
  tMax: number
  span: number
  majorTickMs: number
  minorTickMs: number
  unit: TimelineUnit
}

export interface TimelineBar {
  leftPct: number
  widthPct: number
  start: number
  end: number
}

export type GroupByOption = 'none' | 'assignee' | 'priority' | 'parent' | 'tag'

export interface TaskGroup {
  key: string
  label: string
  tasks: Task[]
}

export interface CriticalPathResult {
  ids: Set<string>
  duration: number
}

export function computeScale(tasks: Task[], now: number = Date.now()): TimelineScale {
  if (tasks.length === 0) {
    return {
      tMin: now - HOUR,
      tMax: now,
      span: HOUR,
      majorTickMs: 10 * MINUTE,
      minorTickMs: MINUTE,
      unit: 'minute',
    }
  }
  let tMin = Infinity
  let tMax = -Infinity
  for (const t of tasks) {
    const start = new Date(t.created_at).getTime()
    const end = t.completed_at ? new Date(t.completed_at).getTime() : now
    if (start < tMin) tMin = start
    if (end > tMax) tMax = end
  }
  // Single task or zero span: pad to 1h so bars remain visible
  if (tMax - tMin < MINUTE) {
    tMax = tMin + HOUR
  }
  const span = tMax - tMin

  if (span < HOUR) return build(tMin, tMax, span, 10 * MINUTE, MINUTE, 'minute')
  if (span < DAY) return build(tMin, tMax, span, HOUR, 15 * MINUTE, 'hour')
  if (span < 7 * DAY) return build(tMin, tMax, span, DAY, 6 * HOUR, 'day')
  if (span < 30 * DAY) return build(tMin, tMax, span, 3 * DAY, DAY, 'day')
  if (span < 180 * DAY) return build(tMin, tMax, span, WEEK, DAY, 'week')
  return build(tMin, tMax, span, 30 * DAY, WEEK, 'month')
}

function build(
  tMin: number,
  tMax: number,
  span: number,
  majorTickMs: number,
  minorTickMs: number,
  unit: TimelineUnit,
): TimelineScale {
  return { tMin, tMax, span, majorTickMs, minorTickMs, unit }
}

export function formatTimelineLabel(ts: number, unit: TimelineUnit): string {
  const d = new Date(ts)
  switch (unit) {
    case 'minute':
    case 'hour':
      return d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })
    case 'day':
    case 'week':
      return `${d.getMonth() + 1}/${d.getDate()}`
    case 'month':
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  }
}

export function computeBar(task: Task, scale: TimelineScale, now: number = Date.now()): TimelineBar {
  const start = new Date(task.created_at).getTime()
  const end = task.completed_at ? new Date(task.completed_at).getTime() : now
  const leftPct = ((start - scale.tMin) / scale.span) * 100
  const widthPct = Math.max(((end - start) / scale.span) * 100, 0.5)
  return { leftPct, widthPct, start, end }
}

// ── Pixel-based projection (Case A horizontal scroll) ──────────
//
// ``computeBar`` returns percent-of-container values which makes
// the timeline always fit the visible width. To support horizontal
// scrolling we project bars onto an absolute pixel space using a
// caller-supplied ``pxPerMs`` zoom factor; total content width is
// ``scale.span * pxPerMs`` and the caller (TaskTimeline) sizes the
// scroll surface accordingly.

export interface TimelineBarPx {
  leftPx: number
  widthPx: number
  start: number
  end: number
}

export function computeBarPx(
  task: Task,
  scale: TimelineScale,
  pxPerMs: number,
  now: number = Date.now(),
): TimelineBarPx {
  const start = new Date(task.created_at).getTime()
  const end = task.completed_at ? new Date(task.completed_at).getTime() : now
  const leftPx = (start - scale.tMin) * pxPerMs
  // Floor at 2px so a zero-duration task is still clickable.
  const widthPx = Math.max((end - start) * pxPerMs, 2)
  return { leftPx, widthPx, start, end }
}

export function tickLeftPx(tickTs: number, scale: TimelineScale, pxPerMs: number): number {
  return (tickTs - scale.tMin) * pxPerMs
}

/** pxPerMs that exactly fits the timeline's time span into ``trackWidthPx``. */
export function fitPxPerMs(scale: TimelineScale, trackWidthPx: number): number {
  if (scale.span <= 0 || trackWidthPx <= 0) return 0
  return trackWidthPx / scale.span
}

export interface TimelineTick {
  ts: number
  major: boolean
}

export function generateTicks(scale: TimelineScale): TimelineTick[] {
  const ticks: TimelineTick[] = []
  const start = Math.ceil(scale.tMin / scale.minorTickMs) * scale.minorTickMs
  const majorStart = Math.ceil(scale.tMin / scale.majorTickMs) * scale.majorTickMs
  const majorSet = new Set<number>()
  for (let t = majorStart; t <= scale.tMax; t += scale.majorTickMs) majorSet.add(t)
  for (let t = start; t <= scale.tMax; t += scale.minorTickMs) {
    ticks.push({ ts: t, major: majorSet.has(t) })
  }
  return ticks
}

const PRIORITY_ORDER: TaskPriority[] = ['urgent', 'high', 'medium', 'low']

const PRIORITY_LABELS: Record<TaskPriority, string> = {
  urgent: '緊急',
  high: '高',
  medium: '中',
  low: '低',
}

export function groupTasks(tasks: Task[], groupBy: GroupByOption): TaskGroup[] {
  if (groupBy === 'none') {
    return [
      {
        key: '__all__',
        label: 'すべて',
        tasks: [...tasks].sort((a, b) => a.sort_order - b.sort_order),
      },
    ]
  }
  const byKey = new Map<string, Task[]>()
  for (const t of tasks) {
    const key = deriveGroupKey(t, groupBy)
    const list = byKey.get(key) ?? []
    list.push(t)
    byKey.set(key, list)
  }
  const keys = Array.from(byKey.keys())
  sortGroupKeys(keys, groupBy)
  return keys.map((key) => ({
    key,
    label: resolveGroupLabel(key, groupBy),
    tasks: byKey.get(key)!.sort((a, b) => a.sort_order - b.sort_order),
  }))
}

function deriveGroupKey(t: Task, groupBy: GroupByOption): string {
  switch (groupBy) {
    case 'assignee':
      return t.assignee_id ?? '__unassigned__'
    case 'priority':
      return t.priority
    case 'parent':
      return t.parent_task_id ?? '__toplevel__'
    case 'tag':
      return t.tags[0] ?? '__untagged__'
    default:
      return '__all__'
  }
}

function sortGroupKeys(keys: string[], groupBy: GroupByOption): void {
  if (groupBy === 'priority') {
    keys.sort(
      (a, b) =>
        PRIORITY_ORDER.indexOf(a as TaskPriority) -
        PRIORITY_ORDER.indexOf(b as TaskPriority),
    )
  } else if (groupBy === 'assignee') {
    keys.sort((a, b) =>
      a === '__unassigned__' ? -1 : b === '__unassigned__' ? 1 : a.localeCompare(b),
    )
  } else {
    keys.sort()
  }
}

function resolveGroupLabel(key: string, groupBy: GroupByOption): string {
  if (key === '__unassigned__') return '未アサイン'
  if (key === '__toplevel__') return 'トップレベル'
  if (key === '__untagged__') return 'タグなし'
  if (key === '__all__') return 'すべて'
  if (groupBy === 'priority') return PRIORITY_LABELS[key as TaskPriority] ?? key
  return key
}

export function formatDuration(ms: number): string {
  if (ms < 0) ms = 0
  if (ms < MINUTE) return `${Math.round(ms / 1000)}s`
  if (ms < HOUR) return `${Math.round(ms / MINUTE)}m`
  if (ms < DAY) {
    const h = Math.floor(ms / HOUR)
    const m = Math.round((ms % HOUR) / MINUTE)
    return m > 0 ? `${h}h ${m}m` : `${h}h`
  }
  const d = Math.floor(ms / DAY)
  const h = Math.round((ms % DAY) / HOUR)
  return h > 0 ? `${d}d ${h}h` : `${d}d`
}

export function computeCriticalPath(tasks: Task[], now: number = Date.now()): CriticalPathResult {
  if (tasks.length === 0) return { ids: new Set(), duration: 0 }

  const taskMap = new Map(tasks.map((t) => [t.id, t]))
  const weight = (t: Task): number => {
    const start = new Date(t.created_at).getTime()
    const end = t.completed_at ? new Date(t.completed_at).getTime() : now
    return Math.max(end - start, 0)
  }

  const outEdges = new Map<string, string[]>()
  const inEdges = new Map<string, string[]>()
  const inDegree = new Map<string, number>()
  for (const t of tasks) {
    inDegree.set(t.id, inDegree.get(t.id) ?? 0)
  }
  for (const t of tasks) {
    for (const target of t.blocks ?? []) {
      if (!taskMap.has(target)) continue
      const outs = outEdges.get(t.id) ?? []
      outs.push(target)
      outEdges.set(t.id, outs)
      const ins = inEdges.get(target) ?? []
      ins.push(t.id)
      inEdges.set(target, ins)
      inDegree.set(target, (inDegree.get(target) ?? 0) + 1)
    }
  }

  // Kahn's topological sort
  const queue: string[] = []
  for (const [id, deg] of inDegree) if (deg === 0) queue.push(id)
  const topo: string[] = []
  const workingDeg = new Map(inDegree)
  while (queue.length > 0) {
    const id = queue.shift()!
    topo.push(id)
    for (const next of outEdges.get(id) ?? []) {
      const d = (workingDeg.get(next) ?? 0) - 1
      workingDeg.set(next, d)
      if (d === 0) queue.push(next)
    }
  }

  // If cycles exist, topo is incomplete — fall back to all tasks
  if (topo.length < tasks.length) {
    for (const t of tasks) if (!topo.includes(t.id)) topo.push(t.id)
  }

  const dist = new Map<string, number>()
  const prev = new Map<string, string | null>()
  for (const id of topo) {
    const t = taskMap.get(id)
    if (!t) continue
    const w = weight(t)
    let best = w
    let bestPrev: string | null = null
    for (const sourceId of inEdges.get(id) ?? []) {
      const cand = (dist.get(sourceId) ?? 0) + w
      if (cand > best) {
        best = cand
        bestPrev = sourceId
      }
    }
    dist.set(id, best)
    prev.set(id, bestPrev)
  }

  let maxDist = -1
  const ends: string[] = []
  for (const [id, d] of dist) {
    if (d > maxDist) {
      maxDist = d
      ends.length = 0
      ends.push(id)
    } else if (d === maxDist) {
      ends.push(id)
    }
  }

  const ids = new Set<string>()
  const stack = [...ends]
  while (stack.length > 0) {
    const id = stack.pop()!
    if (ids.has(id)) continue
    ids.add(id)
    const p = prev.get(id)
    if (p) stack.push(p)
  }
  return { ids, duration: Math.max(maxDist, 0) }
}
