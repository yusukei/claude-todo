import React from 'react'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import TaskCard from './TaskCard'
import type { Task } from '../../types'

interface Props {
  task: Task
  onClick: () => void
  onUpdateFlags: (taskId: string, flags: { needs_detail?: boolean; approved?: boolean }) => void
  onArchive?: (taskId: string, archive: boolean) => void
}

const SortableTaskCard = React.memo(function SortableTaskCard({ task, onClick, onUpdateFlags, onArchive }: Props) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: task.id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      className={`touch-none ${isDragging ? 'opacity-30 z-10' : ''}`}
    >
      <TaskCard
        task={task}
        onClick={onClick}
        onUpdateFlags={onUpdateFlags}
        onArchive={onArchive}
      />
    </div>
  )
})

export default SortableTaskCard
