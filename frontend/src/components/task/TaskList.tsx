import clsx from 'clsx'
import { Calendar } from 'lucide-react'
import type { Task } from '../../types'
import { STATUS_LABELS, STATUS_COLORS, PRIORITY_DOT_COLORS } from '../../constants/task'

interface Props {
  tasks: Task[]
  projectId: string
  onTaskClick: (id: string) => void
}

export default function TaskList({ tasks, projectId, onTaskClick }: Props) {
  return (
    <div className="p-6 overflow-y-auto h-full">
      <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100">
        {tasks.length === 0 && (
          <div className="py-16 text-center text-gray-400">タスクがありません</div>
        )}
        {tasks.map((task) => {
          const isOverdue = task.due_date && new Date(task.due_date) < new Date() && task.status !== 'done'
          return (
            <div
              key={task.id}
              onClick={() => onTaskClick(task.id)}
              className="flex items-center gap-4 px-4 py-3 hover:bg-gray-50 cursor-pointer"
            >
              <span className={clsx('w-2 h-2 rounded-full flex-shrink-0', PRIORITY_DOT_COLORS[task.priority])} />
              <span className="flex-1 text-sm text-gray-800 font-medium">{task.title}</span>
              <div className="flex items-center gap-3 flex-shrink-0">
                {task.tags?.slice(0, 2).map((tag: string) => (
                  <span key={tag} className="text-xs bg-indigo-50 text-indigo-600 px-2 py-0.5 rounded-full hidden sm:block">
                    {tag}
                  </span>
                ))}
                {task.due_date && (
                  <span className={clsx('flex items-center gap-1 text-xs', isOverdue ? 'text-red-500' : 'text-gray-400')}>
                    <Calendar className="w-3 h-3" />
                    {new Date(task.due_date).toLocaleDateString('ja-JP', { month: 'short', day: 'numeric' })}
                  </span>
                )}
                <span className={clsx('text-xs px-2 py-0.5 rounded-full', STATUS_COLORS[task.status])}>
                  {STATUS_LABELS[task.status]}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
