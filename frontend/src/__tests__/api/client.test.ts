import { describe, it, expect, beforeEach, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '../mocks/server'
import { api } from '../../api/client'

describe('api client token refresh', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('401 レスポンスでリフレッシュを実行し、元リクエストをリトライする', async () => {
    localStorage.setItem('access_token', 'expired-token')
    localStorage.setItem('refresh_token', 'valid-refresh')

    let meCallCount = 0
    server.use(
      http.get('/api/v1/auth/me', () => {
        meCallCount++
        if (meCallCount === 1) {
          return HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })
        }
        return HttpResponse.json({ id: 'user-1', email: 'test@test.com', name: 'Test' })
      }),
      http.post('/api/v1/auth/refresh', () =>
        HttpResponse.json({
          access_token: 'new-access-token',
          refresh_token: 'new-refresh-token',
          token_type: 'bearer',
        })
      )
    )

    const response = await api.get('/auth/me')
    expect(response.data.email).toBe('test@test.com')
    expect(localStorage.getItem('access_token')).toBe('new-access-token')
    expect(localStorage.getItem('refresh_token')).toBe('new-refresh-token')
  })

  it('同時 401 で refresh promise を共有する (リフレッシュが1回のみ)', async () => {
    localStorage.setItem('access_token', 'expired-token')
    localStorage.setItem('refresh_token', 'valid-refresh')

    let refreshCallCount = 0
    const meResponses: number[] = []
    const projectsResponses: number[] = []

    server.use(
      http.get('/api/v1/auth/me', () => {
        meResponses.push(1)
        if (meResponses.length === 1) {
          return HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })
        }
        return HttpResponse.json({ id: 'user-1', email: 'test@test.com', name: 'Test' })
      }),
      http.get('/api/v1/projects', () => {
        projectsResponses.push(1)
        if (projectsResponses.length === 1) {
          return HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })
        }
        return HttpResponse.json([{ id: 'p1', name: 'Project' }])
      }),
      http.post('/api/v1/auth/refresh', async () => {
        refreshCallCount++
        await new Promise((r) => setTimeout(r, 50))
        return HttpResponse.json({
          access_token: 'new-access-token',
          refresh_token: 'new-refresh-token',
          token_type: 'bearer',
        })
      })
    )

    const [meRes, projectsRes] = await Promise.all([
      api.get('/auth/me'),
      api.get('/projects'),
    ])

    expect(meRes.data.email).toBe('test@test.com')
    expect(projectsRes.data[0].name).toBe('Project')
    expect(refreshCallCount).toBe(1)
  })

  it('リフレッシュ失敗時にトークンがクリアされる', async () => {
    localStorage.setItem('access_token', 'expired-token')
    localStorage.setItem('refresh_token', 'invalid-refresh')

    let refreshCalled = false
    server.use(
      http.get('/api/v1/auth/me', () =>
        HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })
      ),
      http.post('/api/v1/auth/refresh', () => {
        refreshCalled = true
        return HttpResponse.json({ detail: 'Invalid refresh token' }, { status: 401 })
      })
    )

    try {
      await api.get('/auth/me')
    } catch {
      // エラーが発生することを期待
    }

    // リフレッシュが試行されたことを確認
    expect(refreshCalled).toBe(true)
    // トークンがクリアされていることを確認
    expect(localStorage.getItem('access_token')).toBeNull()
    expect(localStorage.getItem('refresh_token')).toBeNull()
  })
})
