import { http, HttpResponse } from 'msw'
import { createMockUser, createMockTask, createMockProject } from './factories'

export const mockUser = createMockUser()

export const mockRegularUser = createMockUser({
  id: 'user-id-2',
  email: 'user@test.com',
  name: 'Regular User',
  auth_type: 'google',
  is_admin: false,
})

export const mockTokens = {
  access_token: 'mock-access-token',
  refresh_token: 'mock-refresh-token',
  token_type: 'bearer',
}

export const mockProject = createMockProject()

export const mockTask = createMockTask()

/**
 * デフォルトハンドラー (正常系)
 * 各テストで server.use() を使って上書きすることで異常系をテスト可能
 */
export const handlers = [
  // Auth
  http.post('/api/v1/auth/login', () => HttpResponse.json(mockTokens)),
  http.post('/api/v1/auth/refresh', () => HttpResponse.json(mockTokens)),
  http.get('/api/v1/auth/me', () => HttpResponse.json(mockUser)),

  // Projects
  http.get('/api/v1/projects', () => HttpResponse.json([mockProject])),
  http.post('/api/v1/projects', () =>
    HttpResponse.json(mockProject, { status: 201 })
  ),
  http.get('/api/v1/projects/:projectId', () => HttpResponse.json(mockProject)),
  http.patch('/api/v1/projects/:projectId', () => HttpResponse.json(mockProject)),
  http.delete('/api/v1/projects/:projectId', () => new HttpResponse(null, { status: 204 })),

  // Tasks
  http.get('/api/v1/projects/:projectId/tasks', () =>
    HttpResponse.json({ items: [mockTask], total: 1, limit: 200, skip: 0 })
  ),
  http.post('/api/v1/projects/:projectId/tasks', () =>
    HttpResponse.json(mockTask, { status: 201 })
  ),
  http.get('/api/v1/projects/:projectId/tasks/:taskId', () =>
    HttpResponse.json(mockTask)
  ),
  http.patch('/api/v1/projects/:projectId/tasks/:taskId', () =>
    HttpResponse.json(mockTask)
  ),
  http.delete('/api/v1/projects/:projectId/tasks/:taskId', () =>
    new HttpResponse(null, { status: 204 })
  ),

  // Project summary
  http.get('/api/v1/projects/:projectId/summary', () =>
    HttpResponse.json({
      project_id: 'project-id-1',
      total: 3,
      by_status: { todo: 2, done: 1 },
      completion_rate: 33.3,
    })
  ),
]
