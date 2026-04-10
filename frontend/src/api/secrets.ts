/** Project secrets domain API. */
import { api } from './client'

export const secretsApi = {
  list: (projectId: string, params?: { limit?: number; skip?: number }) =>
    api.get(`/projects/${projectId}/secrets/`, { params }).then((r) => r.data),

  create: (projectId: string, data: { key: string; value: string; description?: string }) =>
    api.post(`/projects/${projectId}/secrets/`, data).then((r) => r.data),

  update: (projectId: string, key: string, data: { value?: string; description?: string }) =>
    api.put(`/projects/${projectId}/secrets/${key}`, data).then((r) => r.data),

  remove: (projectId: string, key: string) =>
    api.delete(`/projects/${projectId}/secrets/${key}`).then((r) => r.data),

  getValue: (projectId: string, key: string) =>
    api.get(`/projects/${projectId}/secrets/${key}/value`).then((r) => r.data),
}
