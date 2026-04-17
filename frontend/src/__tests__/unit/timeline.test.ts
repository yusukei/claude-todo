import { describe, expect, it } from 'vitest'
import {
  computeBar,
  computeCriticalPath,
  computeScale,
  formatDuration,
  formatTimelineLabel,
  generateTicks,
  groupTasks,
} from '../../lib/timeline'
import type { Task } from '../../types'

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

function makeTask(overrides: Partial<Task>): Task {
  return {
    id: 't1',
    project_id: 'p1',
    title: 'Task',
    description: null,
    status: 'todo',
    priority: 'medium',
    due_date: null,
    assignee_id: null,
    parent_task_id: null,
    blocks: [],
    blocked_by: [],
    task_type: 'action',
    decision_context: null,
    tags: [],
    comments: [],
    attachments: [],
    is_deleted: false,
    archived: false,
    completion_report: null,
    completed_at: null,
    needs_detail: false,
    approved: false,
    created_by: 'u1',
    created_at: '2026-04-17T00:00:00.000Z',
    updated_at: '2026-04-17T00:00:00.000Z',
    sort_order: 0,
    ...overrides,
  }
}

describe('computeScale', () => {
  it('returns a minute-level scale when span is under an hour', () => {
    const base = Date.parse('2026-04-17T10:00:00Z')
    const tasks = [
      makeTask({ id: 'a', created_at: new Date(base).toISOString() }),
      makeTask({
        id: 'b',
        created_at: new Date(base + 10 * MINUTE).toISOString(),
        completed_at: new Date(base + 20 * MINUTE).toISOString(),
        status: 'done',
      }),
    ]
    const scale = computeScale(tasks, base + 30 * MINUTE)
    expect(scale.unit).toBe('minute')
    expect(scale.majorTickMs).toBe(10 * MINUTE)
    expect(scale.minorTickMs).toBe(MINUTE)
  })

  it('steps up to day ticks for a week-long span', () => {
    const base = Date.parse('2026-04-10T00:00:00Z')
    const tasks = [
      makeTask({ id: 'a', created_at: new Date(base).toISOString() }),
      makeTask({
        id: 'b',
        created_at: new Date(base + 3 * DAY).toISOString(),
        completed_at: new Date(base + 5 * DAY).toISOString(),
        status: 'done',
      }),
    ]
    const scale = computeScale(tasks, base + 6 * DAY)
    expect(scale.unit).toBe('day')
    expect(scale.majorTickMs).toBe(DAY)
  })

  it('pads zero span to keep bars visible', () => {
    const base = Date.parse('2026-04-17T10:00:00Z')
    const tasks = [
      makeTask({
        id: 'a',
        created_at: new Date(base).toISOString(),
        completed_at: new Date(base).toISOString(),
        status: 'done',
      }),
    ]
    const scale = computeScale(tasks, base)
    expect(scale.span).toBeGreaterThan(0)
    expect(scale.tMax).toBe(scale.tMin + HOUR)
  })

  it('falls back to a placeholder scale on empty task list', () => {
    const now = Date.parse('2026-04-17T10:00:00Z')
    const scale = computeScale([], now)
    expect(scale.unit).toBe('minute')
    expect(scale.tMax - scale.tMin).toBe(HOUR)
  })
})

describe('computeBar', () => {
  it('positions a bar proportionally inside the scale', () => {
    const base = Date.parse('2026-04-17T10:00:00Z')
    const tasks = [
      makeTask({ id: 'a', created_at: new Date(base).toISOString() }),
      makeTask({
        id: 'b',
        created_at: new Date(base + 30 * MINUTE).toISOString(),
        completed_at: new Date(base + 60 * MINUTE).toISOString(),
        status: 'done',
      }),
    ]
    const scale = computeScale(tasks, base + 60 * MINUTE)
    const bar = computeBar(tasks[1], scale, base + 60 * MINUTE)
    expect(bar.leftPct).toBeCloseTo(50, 1)
    expect(bar.widthPct).toBeCloseTo(50, 1)
  })

  it('enforces a minimum width so instant tasks stay visible', () => {
    const base = Date.parse('2026-04-17T10:00:00Z')
    const tasks = [
      makeTask({ id: 'a', created_at: new Date(base).toISOString() }),
      makeTask({
        id: 'b',
        created_at: new Date(base + 30 * MINUTE).toISOString(),
        completed_at: new Date(base + 30 * MINUTE).toISOString(),
        status: 'done',
      }),
    ]
    const scale = computeScale(tasks, base + 60 * MINUTE)
    const bar = computeBar(tasks[1], scale, base + 60 * MINUTE)
    expect(bar.widthPct).toBeGreaterThanOrEqual(0.5)
  })
})

describe('formatTimelineLabel', () => {
  it('renders time-of-day for short spans', () => {
    const ts = Date.parse('2026-04-17T10:05:00Z')
    const label = formatTimelineLabel(ts, 'hour')
    expect(label).toMatch(/\d{2}:\d{2}/)
  })

  it('renders month/day for week-scale spans', () => {
    const ts = Date.parse('2026-04-17T10:00:00Z')
    const label = formatTimelineLabel(ts, 'day')
    expect(label).toMatch(/^\d+\/\d+$/)
  })

  it('renders year-month for month-scale spans', () => {
    const ts = Date.parse('2026-04-17T10:00:00Z')
    expect(formatTimelineLabel(ts, 'month')).toMatch(/^\d{4}-\d{2}$/)
  })
})

describe('generateTicks', () => {
  it('produces both minor and major ticks within range', () => {
    const base = Date.parse('2026-04-17T10:00:00Z')
    const scale = computeScale(
      [
        makeTask({ id: 'a', created_at: new Date(base).toISOString() }),
        makeTask({
          id: 'b',
          created_at: new Date(base + 30 * MINUTE).toISOString(),
          completed_at: new Date(base + 50 * MINUTE).toISOString(),
          status: 'done',
        }),
      ],
      base + 50 * MINUTE,
    )
    const ticks = generateTicks(scale)
    expect(ticks.length).toBeGreaterThan(0)
    expect(ticks.some((t) => t.major)).toBe(true)
  })
})

describe('groupTasks', () => {
  it('returns a single bucket when grouping is disabled', () => {
    const tasks = [makeTask({ id: 'a' }), makeTask({ id: 'b', sort_order: 1 })]
    const groups = groupTasks(tasks, 'none')
    expect(groups).toHaveLength(1)
    expect(groups[0].tasks).toHaveLength(2)
  })

  it('keeps priority buckets ordered urgent → low', () => {
    const tasks = [
      makeTask({ id: 'a', priority: 'low' }),
      makeTask({ id: 'b', priority: 'urgent' }),
      makeTask({ id: 'c', priority: 'medium' }),
    ]
    const groups = groupTasks(tasks, 'priority')
    expect(groups.map((g) => g.key)).toEqual(['urgent', 'medium', 'low'])
  })

  it('labels unassigned tasks distinctly for assignee grouping', () => {
    const tasks = [
      makeTask({ id: 'a', assignee_id: null }),
      makeTask({ id: 'b', assignee_id: 'user-1' }),
    ]
    const groups = groupTasks(tasks, 'assignee')
    expect(groups[0].key).toBe('__unassigned__')
    expect(groups[0].label).toBe('未アサイン')
  })
})

describe('formatDuration', () => {
  it('formats sub-minute durations as seconds', () => {
    expect(formatDuration(5_000)).toBe('5s')
  })
  it('formats hours and remaining minutes', () => {
    expect(formatDuration(HOUR + 15 * MINUTE)).toBe('1h 15m')
  })
  it('formats multi-day durations', () => {
    expect(formatDuration(2 * DAY + 3 * HOUR)).toBe('2d 3h')
  })
})

describe('computeCriticalPath', () => {
  it('returns an empty result for an empty task list', () => {
    const res = computeCriticalPath([], Date.parse('2026-04-17T10:00:00Z'))
    expect(res.ids.size).toBe(0)
    expect(res.duration).toBe(0)
  })

  it('identifies the longest dependency chain', () => {
    const base = Date.parse('2026-04-17T00:00:00Z')
    const tasks = [
      makeTask({
        id: 'a',
        created_at: new Date(base).toISOString(),
        completed_at: new Date(base + 2 * HOUR).toISOString(),
        status: 'done',
        blocks: ['b'],
      }),
      makeTask({
        id: 'b',
        created_at: new Date(base + 2 * HOUR).toISOString(),
        completed_at: new Date(base + 6 * HOUR).toISOString(),
        status: 'done',
        blocks: ['c'],
        blocked_by: ['a'],
      }),
      makeTask({
        id: 'c',
        created_at: new Date(base + 6 * HOUR).toISOString(),
        completed_at: new Date(base + 7 * HOUR).toISOString(),
        status: 'done',
        blocked_by: ['b'],
      }),
      makeTask({
        id: 'd',
        created_at: new Date(base).toISOString(),
        completed_at: new Date(base + 3 * HOUR).toISOString(),
        status: 'done',
      }),
    ]
    const res = computeCriticalPath(tasks, base + 7 * HOUR)
    expect(res.ids.has('a')).toBe(true)
    expect(res.ids.has('b')).toBe(true)
    expect(res.ids.has('c')).toBe(true)
    expect(res.ids.has('d')).toBe(false)
    expect(res.duration).toBe(7 * HOUR)
  })

  it('survives cyclic blocks without hanging', () => {
    const base = Date.parse('2026-04-17T00:00:00Z')
    const tasks = [
      makeTask({
        id: 'a',
        created_at: new Date(base).toISOString(),
        completed_at: new Date(base + HOUR).toISOString(),
        status: 'done',
        blocks: ['b'],
      }),
      makeTask({
        id: 'b',
        created_at: new Date(base).toISOString(),
        completed_at: new Date(base + HOUR).toISOString(),
        status: 'done',
        blocks: ['a'],
      }),
    ]
    const res = computeCriticalPath(tasks, base + HOUR)
    expect(res.duration).toBeGreaterThan(0)
  })
})
