import React from 'react'
import { useDraggable } from '@dnd-kit/core'
import { CSS } from '@dnd-kit/utilities'
import TaskCard from './TaskCard'
import type { Task } from '../../types'

interface Props {
  task: Task
  onClick: () => void
  onUpdateFlags: (taskId: string, flags: { needs_detail?: boolean; approved?: boolean }) => void
  onArchive?: (taskId: string, archive: boolean) => void
}

const DraggableTaskCard = React.memo(function DraggableTaskCard({ task, onClick, onUpdateFlags, onArchive }: Props) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: task.id,
  })

  const style = {
    transform: CSS.Translate.toString(transform),
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      {...listeners}
      {...attributes}
      className={`touch-none ${isDragging ? 'opacity-30' : ''}`}
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

export default DraggableTaskCard
