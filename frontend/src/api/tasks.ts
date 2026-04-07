/**
 * Tasks domain API. Wraps /tasks endpoints with typed return values
 * so query/mutation callers don't have to repeat the URL strings.
 */
import { api } from './client'
import type { Task } from '../types'

export interface ListTasksParams {
  project_id?: string
  status?: string
  parent_task_id?: string
  archived?: boolean
  limit?: number
  skip?: number
  sort_by?: string
  order?: 'asc' | 'desc'
}

export interface ListTasksResponse {
  items: Task[]
  total: number
  limit: number
  skip: number
}

export const tasksApi = {
  list: (params?: ListTasksParams) =>
    api.get<ListTasksResponse>('/tasks', { params }).then((r) => r.data),

  get: (id: string) => api.get<Task>(`/tasks/${id}`).then((r) => r.data),

  create: (data: Partial<Task>) =>
    api.post<Task>('/tasks', data).then((r) => r.data),

  update: (id: string, data: Partial<Task>) =>
    api.patch<Task>(`/tasks/${id}`, data).then((r) => r.data),

  remove: (id: string) => api.delete(`/tasks/${id}`).then((r) => r.data),

  archive: (id: string) =>
    api.post(`/tasks/${id}/archive`).then((r) => r.data),

  unarchive: (id: string) =>
    api.post(`/tasks/${id}/unarchive`).then((r) => r.data),

  addComment: (id: string, content: string) =>
    api.post(`/tasks/${id}/comments`, { content }).then((r) => r.data),

  deleteComment: (taskId: string, commentId: string) =>
    api.delete(`/tasks/${taskId}/comments/${commentId}`).then((r) => r.data),
}
