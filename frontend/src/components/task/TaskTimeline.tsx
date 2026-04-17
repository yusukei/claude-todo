import { useEffect, useLayoutEffect, useMemo, useState, useRef, useCallback, memo } from 'react'
import { List } from 'react-window'
import clsx from 'clsx'
import { CornerDownRight } from 'lucide-react'
import type { Task } from '../../types'
import {
  computeBar,
  computeCriticalPath,
  computeScale,
  formatDuration,
  formatTimelineLabel,
  generateTicks,
  groupTasks,
  type GroupByOption,
  type TaskGroup,
  type TimelineScale,
} from '../../lib/timeline'
import { STATUS_LABELS } from '../../constants/task'

const ROW_HEIGHT = 28
const LABEL_COL_WIDTH = 220
const VIRTUALIZE_THRESHOLD = 100

interface Props {
  tasks: Task[]
  projectId: string
  onTaskClick: (taskId: string) => void
  groupBy?: GroupByOption
  onGroupByChange?: (value: GroupByOption) => void
  highlightCritical?: boolean
  onHighlightCriticalChange?: (value: boolean) => void
}

type FlatRow =
  | { kind: 'group-header'; groupKey: string; label: string; count: number }
  | { kind: 'task'; task: Task }

const STATUS_BAR_CLASSES: Record<Task['status'], string> = {
  todo: 'bg-gray-400 dark:bg-gray-500',
  in_progress: 'bg-blue-500 dark:bg-blue-400 motion-safe:animate-pulse',
  on_hold: 'bg-amber-500 dark:bg-amber-400',
  done: 'bg-emerald-500 dark:bg-emerald-400',
  cancelled: 'bg-red-400 dark:bg-red-500 timeline-bar-cancelled',
}

export default function TaskTimeline({
  tasks,
  projectId: _projectId,
  onTaskClick,
  groupBy = 'none',
  onGroupByChange,
  highlightCritical = false,
  onHighlightCriticalChange,
}: Props) {
  // Force re-render every 30s so in-progress bar right edges track "now"
  const [, setTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setTick((x) => x + 1), 30_000)
    return () => clearInterval(id)
  }, [])

  const now = Date.now()
  const scale = useMemo(() => computeScale(tasks, now), [tasks, now])
  const groups = useMemo(() => groupTasks(tasks, groupBy), [tasks, groupBy])
  const ticks = useMemo(() => generateTicks(scale), [scale])
  const critical = useMemo(
    () => (highlightCritical ? computeCriticalPath(tasks, now) : null),
    [tasks, now, highlightCritical],
  )

  const rows = useMemo<FlatRow[]>(() => flattenRows(groups, groupBy), [groups, groupBy])
  const rowIndexById = useMemo(() => {
    const m = new Map<string, number>()
    rows.forEach((r, i) => {
      if (r.kind === 'task') m.set(r.task.id, i)
    })
    return m
  }, [rows])

  const [hoverTask, setHoverTask] = useState<Task | null>(null)
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const handleBarEnter = useCallback((task: Task, e: React.MouseEvent) => {
    setHoverTask(task)
    setHoverPos({ x: e.clientX, y: e.clientY })
  }, [])
  const handleBarMove = useCallback((e: React.MouseEvent) => {
    setHoverPos({ x: e.clientX, y: e.clientY })
  }, [])
  const handleBarLeave = useCallback(() => {
    setHoverTask(null)
    setHoverPos(null)
  }, [])

  if (tasks.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400 dark:text-gray-500">
        タスクがありません
      </div>
    )
  }

  const totalRows = rows.length
  const virtualize = totalRows >= VIRTUALIZE_THRESHOLD

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <TimelineToolbar
        groupBy={groupBy}
        onGroupByChange={onGroupByChange}
        highlightCritical={highlightCritical}
        onHighlightCriticalChange={onHighlightCriticalChange}
        criticalDurationMs={critical?.duration ?? null}
      />

      <div ref={scrollRef} className="flex-1 overflow-auto relative">
        <TimelineAxis
          ticks={ticks}
          scale={scale}
          totalRows={totalRows}
          rowHeight={ROW_HEIGHT}
          labelColWidth={LABEL_COL_WIDTH}
        />

        <div className="relative" style={{ height: totalRows * ROW_HEIGHT }}>
          {virtualize ? (
            <List
              style={{ height: Math.min(600, totalRows * ROW_HEIGHT), width: '100%' }}
              rowCount={totalRows}
              rowHeight={ROW_HEIGHT}
              rowComponent={VirtualRow}
              rowProps={{
                rows,
                scale,
                onTaskClick,
                onBarEnter: handleBarEnter,
                onBarMove: handleBarMove,
                onBarLeave: handleBarLeave,
                criticalIds: critical?.ids ?? null,
                now,
              }}
            />
          ) : (
            rows.map((row, idx) => (
              <TimelineRow
                key={rowKey(row, idx)}
                row={row}
                scale={scale}
                style={{ top: idx * ROW_HEIGHT, height: ROW_HEIGHT }}
                onTaskClick={onTaskClick}
                onBarEnter={handleBarEnter}
                onBarMove={handleBarMove}
                onBarLeave={handleBarLeave}
                critical={critical?.ids.has(row.kind === 'task' ? row.task.id : '') ?? false}
                now={now}
              />
            ))
          )}

          <TimelineArrows
            tasks={tasks}
            scale={scale}
            rowIndexById={rowIndexById}
            criticalIds={critical?.ids ?? null}
          />
        </div>
      </div>

      {hoverTask && hoverPos && <TimelineTooltip task={hoverTask} pos={hoverPos} now={now} />}
    </div>
  )
}

function flattenRows(groups: TaskGroup[], groupBy: GroupByOption): FlatRow[] {
  const rows: FlatRow[] = []
  for (const g of groups) {
    if (g.tasks.length === 0) continue
    if (groupBy !== 'none') {
      rows.push({ kind: 'group-header', groupKey: g.key, label: g.label, count: g.tasks.length })
    }
    for (const t of g.tasks) rows.push({ kind: 'task', task: t })
  }
  return rows
}

function rowKey(row: FlatRow, idx: number): string {
  return row.kind === 'task' ? row.task.id : `group:${row.groupKey}:${idx}`
}

interface VirtualRowProps {
  rows: FlatRow[]
  scale: TimelineScale
  onTaskClick: (id: string) => void
  onBarEnter: (task: Task, e: React.MouseEvent) => void
  onBarMove: (e: React.MouseEvent) => void
  onBarLeave: () => void
  criticalIds: Set<string> | null
  now: number
}

type VirtualRowRenderProps = VirtualRowProps & {
  index: number
  style: React.CSSProperties
  ariaAttributes: {
    'aria-posinset': number
    'aria-setsize': number
    role: 'listitem'
  }
}

function VirtualRow({
  index,
  style,
  rows,
  scale,
  onTaskClick,
  onBarEnter,
  onBarMove,
  onBarLeave,
  criticalIds,
  now,
}: VirtualRowRenderProps) {
  const row = rows[index]
  return (
    <TimelineRow
      row={row}
      scale={scale}
      style={style}
      onTaskClick={onTaskClick}
      onBarEnter={onBarEnter}
      onBarMove={onBarMove}
      onBarLeave={onBarLeave}
      critical={row.kind === 'task' ? criticalIds?.has(row.task.id) ?? false : false}
      now={now}
    />
  )
}

interface TimelineRowProps {
  row: FlatRow
  scale: TimelineScale
  style: React.CSSProperties
  onTaskClick: (id: string) => void
  onBarEnter: (task: Task, e: React.MouseEvent) => void
  onBarMove: (e: React.MouseEvent) => void
  onBarLeave: () => void
  critical: boolean
  now: number
}

const TimelineRow = memo(function TimelineRow({
  row,
  scale,
  style,
  onTaskClick,
  onBarEnter,
  onBarMove,
  onBarLeave,
  critical,
  now,
}: TimelineRowProps) {
  if (row.kind === 'group-header') {
    return (
      <div
        className="absolute left-0 right-0 flex items-center bg-gray-50 dark:bg-gray-800/80 border-b border-gray-200 dark:border-gray-700 px-3 text-xs font-semibold text-gray-600 dark:text-gray-300"
        style={style}
      >
        {row.label}
        <span className="ml-2 text-gray-400 dark:text-gray-500 font-normal">
          {row.count}件
        </span>
      </div>
    )
  }

  const task = row.task
  const bar = computeBar(task, scale, now)
  const isSubtask = task.parent_task_id != null

  return (
    <div
      className="absolute left-0 right-0 flex items-stretch hover:bg-gray-50 dark:hover:bg-gray-700/40"
      style={style}
    >
      <div
        className={clsx(
          'flex items-center gap-1.5 shrink-0 px-2 text-xs text-gray-700 dark:text-gray-200 truncate cursor-pointer',
          isSubtask && 'pl-6 text-gray-500 dark:text-gray-400',
        )}
        style={{ width: LABEL_COL_WIDTH }}
        onClick={() => onTaskClick(task.id)}
        title={task.title}
      >
        {isSubtask && <CornerDownRight className="w-3 h-3 shrink-0" />}
        <span className="truncate">{task.title}</span>
      </div>
      <div className="relative flex-1 border-b border-gray-100 dark:border-gray-800">
        <button
          type="button"
          data-testid={`timeline-bar-${task.id}`}
          className={clsx(
            'absolute top-1 h-[20px] rounded cursor-pointer transition-shadow',
            STATUS_BAR_CLASSES[task.status],
            critical && 'ring-2 ring-emerald-300 dark:ring-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]',
            'hover:scale-y-110 hover:shadow-md',
          )}
          style={{
            left: `${bar.leftPct}%`,
            width: `${bar.widthPct}%`,
          }}
          onMouseEnter={(e) => onBarEnter(task, e)}
          onMouseMove={onBarMove}
          onMouseLeave={onBarLeave}
          onClick={() => onTaskClick(task.id)}
          aria-label={`${task.title} (${STATUS_LABELS[task.status]})`}
        />
      </div>
    </div>
  )
})

interface TimelineAxisProps {
  ticks: { ts: number; major: boolean }[]
  scale: TimelineScale
  totalRows: number
  rowHeight: number
  labelColWidth: number
}

function TimelineAxis({ ticks, scale, totalRows, rowHeight, labelColWidth }: TimelineAxisProps) {
  return (
    <div className="sticky top-0 z-10 flex h-7 bg-gray-100 dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
      <div
        className="shrink-0 px-2 text-xs font-semibold text-gray-500 dark:text-gray-400 flex items-center"
        style={{ width: labelColWidth }}
      >
        タスク
      </div>
      <div
        className="relative flex-1 overflow-hidden"
        aria-hidden={totalRows === 0}
      >
        {ticks.map((tick) => (
          <div
            key={tick.ts}
            className={clsx(
              'absolute top-0 bottom-0 border-l',
              tick.major
                ? 'border-gray-300 dark:border-gray-600'
                : 'border-gray-100 dark:border-gray-800',
            )}
            style={{ left: `${((tick.ts - scale.tMin) / scale.span) * 100}%` }}
          >
            {tick.major && (
              <span className="absolute top-0.5 left-1 text-[10px] text-gray-500 dark:text-gray-400 whitespace-nowrap">
                {formatTimelineLabel(tick.ts, scale.unit)}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

interface TimelineArrowsProps {
  tasks: Task[]
  scale: TimelineScale
  rowIndexById: Map<string, number>
  criticalIds: Set<string> | null
}

function TimelineArrows({ tasks, scale, rowIndexById, criticalIds }: TimelineArrowsProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [trackWidth, setTrackWidth] = useState(0)

  useLayoutEffect(() => {
    const el = containerRef.current
    if (!el) return
    const update = () => setTrackWidth(el.clientWidth)
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const edges = useMemo(() => {
    const byId = new Map(tasks.map((t) => [t.id, t]))
    const result: { from: Task; to: Task; critical: boolean }[] = []
    for (const src of tasks) {
      for (const targetId of src.blocks ?? []) {
        const tgt = byId.get(targetId)
        if (!tgt) continue
        const crit =
          criticalIds != null && criticalIds.has(src.id) && criticalIds.has(tgt.id)
        result.push({ from: src, to: tgt, critical: crit })
      }
    }
    return result
  }, [tasks, criticalIds])

  if (edges.length === 0 && trackWidth > 0) {
    return (
      <div
        ref={containerRef}
        aria-hidden
        className="absolute top-0 bottom-0 pointer-events-none"
        style={{ left: LABEL_COL_WIDTH, right: 0 }}
      />
    )
  }

  return (
    <div
      ref={containerRef}
      aria-hidden
      className="absolute top-0 bottom-0 pointer-events-none"
      style={{ left: LABEL_COL_WIDTH, right: 0 }}
    >
      {trackWidth > 0 && edges.length > 0 && (
        <svg
          width={trackWidth}
          height="100%"
          style={{ position: 'absolute', inset: 0 }}
        >
          <defs>
            <marker
              id="timeline-arrow"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto"
            >
              <path d="M0,0 L10,5 L0,10 z" fill="#94a3b8" />
            </marker>
            <marker
              id="timeline-arrow-critical"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto"
            >
              <path d="M0,0 L10,5 L0,10 z" fill="#10b981" />
            </marker>
          </defs>
          {edges.map((edge, i) => {
            const srcIdx = rowIndexById.get(edge.from.id)
            const tgtIdx = rowIndexById.get(edge.to.id)
            if (srcIdx == null || tgtIdx == null) return null
            const srcBar = computeBar(edge.from, scale)
            const tgtBar = computeBar(edge.to, scale)
            const x1 = ((srcBar.leftPct + srcBar.widthPct) / 100) * trackWidth
            const x2 = (tgtBar.leftPct / 100) * trackWidth
            const y1 = srcIdx * ROW_HEIGHT + ROW_HEIGHT / 2
            const y2 = tgtIdx * ROW_HEIGHT + ROW_HEIGHT / 2
            const cp1x = x1 + 40
            const cp2x = x2 - 40
            const d = `M ${x1} ${y1} C ${cp1x} ${y1}, ${cp2x} ${y2}, ${x2} ${y2}`
            return (
              <path
                key={i}
                d={d}
                fill="none"
                stroke={edge.critical ? '#10b981' : '#94a3b8'}
                strokeWidth={edge.critical ? 2 : 1.25}
                markerEnd={
                  edge.critical
                    ? 'url(#timeline-arrow-critical)'
                    : 'url(#timeline-arrow)'
                }
              />
            )
          })}
        </svg>
      )}
    </div>
  )
}

interface TimelineTooltipProps {
  task: Task
  pos: { x: number; y: number }
  now: number
}

function TimelineTooltip({ task, pos, now }: TimelineTooltipProps) {
  const start = new Date(task.created_at).getTime()
  const end = task.completed_at ? new Date(task.completed_at).getTime() : now
  const duration = formatDuration(end - start)
  return (
    <div
      role="tooltip"
      className="fixed z-50 pointer-events-none px-3 py-2 rounded-lg shadow-xl bg-gray-900 text-gray-100 text-xs max-w-xs"
      style={{ left: pos.x + 12, top: pos.y - 12 }}
    >
      <div className="font-semibold truncate">{task.title}</div>
      <div className="mt-1 flex items-center gap-2 text-[11px]">
        <span className="px-1.5 py-0.5 rounded bg-gray-700">
          {STATUS_LABELS[task.status]}
        </span>
        <span className="text-gray-300">{duration}</span>
      </div>
      {task.active_form && (
        <div className="mt-1 text-gray-300 text-[11px] italic truncate">
          {task.active_form}
        </div>
      )}
      {task.assignee_id && (
        <div className="mt-0.5 text-gray-400 text-[11px]">
          担当: {task.assignee_id}
        </div>
      )}
    </div>
  )
}

interface TimelineToolbarProps {
  groupBy: GroupByOption
  onGroupByChange?: (value: GroupByOption) => void
  highlightCritical: boolean
  onHighlightCriticalChange?: (value: boolean) => void
  criticalDurationMs: number | null
}

function TimelineToolbar({
  groupBy,
  onGroupByChange,
  highlightCritical,
  onHighlightCriticalChange,
  criticalDurationMs,
}: TimelineToolbarProps) {
  return (
    <div className="flex items-center gap-3 px-4 py-2 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/60 text-sm">
      <label className="flex items-center gap-1.5 text-gray-600 dark:text-gray-300">
        <span className="text-xs">グループ:</span>
        <select
          value={groupBy}
          onChange={(e) => onGroupByChange?.(e.target.value as GroupByOption)}
          className="text-xs border border-gray-200 dark:border-gray-600 rounded px-1.5 py-0.5 bg-white dark:bg-gray-700 text-gray-700 dark:text-gray-200 focus:outline-none focus:ring-2 focus:ring-focus"
        >
          <option value="none">なし</option>
          <option value="assignee">担当者</option>
          <option value="priority">優先度</option>
          <option value="parent">親タスク</option>
          <option value="tag">タグ</option>
        </select>
      </label>
      <label className="flex items-center gap-1.5 text-gray-600 dark:text-gray-300 cursor-pointer">
        <input
          type="checkbox"
          checked={highlightCritical}
          onChange={(e) => onHighlightCriticalChange?.(e.target.checked)}
          className="rounded border-gray-300 dark:border-gray-600 text-terracotta-600 focus:ring-focus w-3.5 h-3.5"
        />
        <span className="text-xs">クリティカルパス強調</span>
      </label>
      {highlightCritical && criticalDurationMs != null && criticalDurationMs > 0 && (
        <span className="text-xs text-gray-500 dark:text-gray-400">
          最長経路: {formatDuration(criticalDurationMs)}
        </span>
      )}
    </div>
  )
}
