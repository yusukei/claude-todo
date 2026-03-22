import type { TaskStatus, TaskPriority } from '../types'

export const STATUS_LABELS: Record<TaskStatus, string> = {
  todo: 'TODO',
  in_progress: '進行中',
  in_review: 'レビュー中',
  done: '完了',
  cancelled: 'キャンセル',
}

export const STATUS_COLORS: Record<TaskStatus, string> = {
  todo: 'bg-gray-100 text-gray-600',
  in_progress: 'bg-blue-100 text-blue-700',
  in_review: 'bg-yellow-100 text-yellow-700',
  done: 'bg-green-100 text-green-700',
  cancelled: 'bg-red-100 text-red-600',
}

export const STATUS_BG_COLORS: Record<TaskStatus, string> = {
  todo: 'bg-gray-100',
  in_progress: 'bg-blue-100',
  in_review: 'bg-yellow-100',
  done: 'bg-green-100',
  cancelled: 'bg-red-100',
}

export const PRIORITY_COLORS: Record<TaskPriority, string> = {
  urgent: 'bg-red-100 text-red-700',
  high: 'bg-orange-100 text-orange-700',
  medium: 'bg-yellow-100 text-yellow-700',
  low: 'bg-gray-100 text-gray-600',
}

export const PRIORITY_DOT_COLORS: Record<TaskPriority, string> = {
  urgent: 'bg-red-500',
  high: 'bg-orange-500',
  medium: 'bg-yellow-500',
  low: 'bg-gray-400',
}

export const PRIORITY_LABELS: Record<TaskPriority, string> = {
  urgent: '緊急',
  high: '高',
  medium: '中',
  low: '低',
}

export const STATUS_OPTIONS = [
  { value: 'todo' as TaskStatus, label: 'TODO' },
  { value: 'in_progress' as TaskStatus, label: '進行中' },
  { value: 'in_review' as TaskStatus, label: 'レビュー中' },
  { value: 'done' as TaskStatus, label: '完了' },
  { value: 'cancelled' as TaskStatus, label: 'キャンセル' },
]

export const PRIORITY_OPTIONS = [
  { value: 'low' as TaskPriority, label: '低' },
  { value: 'medium' as TaskPriority, label: '中' },
  { value: 'high' as TaskPriority, label: '高' },
  { value: 'urgent' as TaskPriority, label: '緊急' },
]

export const BOARD_COLUMNS: { key: TaskStatus; label: string; color: string }[] = [
  { key: 'todo', label: 'TODO', color: 'bg-gray-100' },
  { key: 'in_progress', label: '進行中', color: 'bg-blue-100' },
  { key: 'in_review', label: 'レビュー中', color: 'bg-yellow-100' },
  { key: 'done', label: '完了', color: 'bg-green-100' },
]
