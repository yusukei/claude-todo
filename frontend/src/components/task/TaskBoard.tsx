import { useMemo } from 'react'
import TaskCard from './TaskCard'
import type { Task } from '../../types'
import { BOARD_COLUMNS } from '../../constants/task'

interface Props {
  tasks: Task[]
  projectId: string
  onTaskClick: (id: string) => void
}

export default function TaskBoard({ tasks, projectId, onTaskClick }: Props) {
  const tasksByStatus = useMemo(() => {
    const map: Record<string, Task[]> = {}
    for (const col of BOARD_COLUMNS) map[col.key] = []
    for (const t of tasks) {
      if (map[t.status]) map[t.status].push(t)
    }
    return map
  }, [tasks])

  return (
    <div className="flex gap-4 p-6 h-full overflow-x-auto">
      {BOARD_COLUMNS.map((col) => {
        const colTasks = tasksByStatus[col.key] ?? []
        return (
          <div key={col.key} className="flex-shrink-0 w-72 flex flex-col">
            <div className={`flex items-center gap-2 px-3 py-2 rounded-lg mb-3 ${col.color}`}>
              <span className="text-sm font-semibold text-gray-700">{col.label}</span>
              <span className="text-xs text-gray-500 bg-white/60 px-1.5 py-0.5 rounded-full">
                {colTasks.length}
              </span>
            </div>
            <div className="flex-1 space-y-2 overflow-y-auto pr-1">
              {colTasks.map((task) => (
                <TaskCard key={task.id} task={task} onClick={() => onTaskClick(task.id)} />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
