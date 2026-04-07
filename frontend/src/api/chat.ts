/** Chat session/messages domain API. */
import { api } from './client'

export interface ChatSession {
  id: string
  project_id: string
  title: string
  status: string
  model: string
  working_dir: string
  created_at: string
  updated_at: string
}

export const chatApi = {
  listSessions: (projectId?: string) =>
    api
      .get<ChatSession[]>('/chat/sessions', {
        params: projectId ? { project_id: projectId } : undefined,
      })
      .then((r) => r.data),

  getSession: (id: string) =>
    api.get<ChatSession>(`/chat/sessions/${id}`).then((r) => r.data),

  createSession: (data: { project_id: string; title?: string; model?: string }) =>
    api.post<ChatSession>('/chat/sessions', data).then((r) => r.data),

  updateSession: (id: string, data: { title?: string; model?: string }) =>
    api.patch<ChatSession>(`/chat/sessions/${id}`, data).then((r) => r.data),

  deleteSession: (id: string) =>
    api.delete(`/chat/sessions/${id}`).then((r) => r.data),

  getMessages: (
    sessionId: string,
    params?: { limit?: number; skip?: number },
  ) =>
    api
      .get(`/chat/sessions/${sessionId}/messages`, { params })
      .then((r) => r.data),
}
