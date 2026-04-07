/** Knowledge base domain API. */
import { api } from './client'

export const knowledgeApi = {
  list: (params?: { category?: string; limit?: number; skip?: number }) =>
    api.get('/knowledge', { params }).then((r) => r.data),

  get: (id: string) => api.get(`/knowledge/${id}`).then((r) => r.data),

  create: (data: Record<string, unknown>) =>
    api.post('/knowledge', data).then((r) => r.data),

  update: (id: string, data: Record<string, unknown>) =>
    api.patch(`/knowledge/${id}`, data).then((r) => r.data),

  remove: (id: string) => api.delete(`/knowledge/${id}`).then((r) => r.data),

  search: (q: string, params?: { category?: string; limit?: number }) =>
    api.get('/knowledge/search', { params: { q, ...params } }).then((r) => r.data),
}
