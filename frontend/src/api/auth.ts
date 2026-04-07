/** Authentication / current-user domain API. */
import { api } from './client'

export const authApi = {
  me: () => api.get('/auth/me').then((r) => r.data),

  login: (email: string, password: string) =>
    api.post('/auth/login', { email, password }).then((r) => r.data),

  logout: () => api.post('/auth/logout').then((r) => r.data),

  refresh: (refresh_token: string) =>
    api.post('/auth/refresh', { refresh_token }).then((r) => r.data),

  changePassword: (current_password: string, new_password: string) =>
    api
      .post('/auth/change-password', { current_password, new_password })
      .then((r) => r.data),
}
