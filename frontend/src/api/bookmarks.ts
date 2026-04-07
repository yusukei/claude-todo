/** Bookmarks + collections domain API. */
import { api } from './client'

export const bookmarksApi = {
  list: (params?: { collection_id?: string; limit?: number; skip?: number }) =>
    api.get('/bookmarks', { params }).then((r) => r.data),

  get: (id: string) => api.get(`/bookmarks/${id}`).then((r) => r.data),

  create: (data: { url: string; collection_id?: string; title?: string }) =>
    api.post('/bookmarks', data).then((r) => r.data),

  update: (id: string, data: Record<string, unknown>) =>
    api.patch(`/bookmarks/${id}`, data).then((r) => r.data),

  remove: (id: string) => api.delete(`/bookmarks/${id}`).then((r) => r.data),

  search: (q: string) =>
    api.get('/bookmarks/search', { params: { q } }).then((r) => r.data),
}

export const bookmarkCollectionsApi = {
  list: () => api.get('/bookmark-collections').then((r) => r.data),
  get: (id: string) =>
    api.get(`/bookmark-collections/${id}`).then((r) => r.data),
  create: (data: { name: string }) =>
    api.post('/bookmark-collections', data).then((r) => r.data),
  update: (id: string, data: Record<string, unknown>) =>
    api.patch(`/bookmark-collections/${id}`, data).then((r) => r.data),
  remove: (id: string) =>
    api.delete(`/bookmark-collections/${id}`).then((r) => r.data),
}
