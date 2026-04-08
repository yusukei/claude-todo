import axios from 'axios'
import { useAuthStore } from '../store/auth'

/**
 * Axios instance for the REST API.
 *
 * Authentication is handled via HttpOnly cookies set by the backend
 * (`access_token` + `refresh_token`). The frontend never reads or stores
 * tokens directly — `withCredentials: true` lets the browser ship the
 * cookies on every request, and the response interceptor reissues them
 * via `/auth/refresh` when the access token expires.
 */
export const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true,
})

let refreshPromise: Promise<void> | null = null

// URLs that must NOT trigger the auto-refresh interceptor: refreshing
// after a refresh-failure leads to an obvious infinite loop, and posting
// to /auth/logout when we are already logged out is meaningless and used
// to ricochet through the same loop because the 401 from /auth/logout
// would itself fire the refresh handler again.
const AUTH_LOOP_PATHS = ['/auth/refresh', '/auth/logout']

function isAuthLoopUrl(url: string | undefined): boolean {
  if (!url) return false
  return AUTH_LOOP_PATHS.some((p) => url.includes(p))
}

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const cfg = error.config
    if (
      error.response?.status === 401 &&
      cfg &&
      !cfg._retried &&
      !isAuthLoopUrl(cfg.url)
    ) {
      cfg._retried = true

      // Coalesce concurrent refresh attempts so a burst of 401s only
      // triggers one /auth/refresh round-trip.
      if (!refreshPromise) {
        refreshPromise = (async () => {
          try {
            await axios.post(
              '/api/v1/auth/refresh',
              {},
              { withCredentials: true },
            )
          } catch {
            // Refresh failed → drop local user state but do NOT call
            // /auth/logout. The server cookies are already invalid (or
            // we wouldn't be here), and hitting /auth/logout would
            // itself 401 and re-enter this very interceptor.
            useAuthStore.getState().setUser(null)
            throw new Error('Refresh failed')
          } finally {
            refreshPromise = null
          }
        })()
      }

      try {
        await refreshPromise
      } catch {
        return Promise.reject(error)
      }

      // Cookie has been refreshed; retry the original request.
      return api.request(cfg)
    }
    return Promise.reject(error)
  },
)
