import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { api } from '../../api/client'
import { useAuthStore } from '../../store/auth'

/**
 * Bootstraps authentication state on first mount.
 *
 * Authentication is cookie-based, so we can't tell from JS whether a
 * valid session exists. The bootstrap simply asks the server: a 200
 * from `/auth/me` populates the user, anything else (including 401)
 * leaves the user null. The store always ends up with
 * `isInitialized=true` so route guards stop blocking.
 *
 * Lives in its own file (extracted from App.tsx) so the boot sequence
 * can be unit-tested in isolation without dragging in the full router.
 */
export default function AppInit({ children }: { children: ReactNode }) {
  const setUser = useAuthStore((s) => s.setUser)
  const setInitialized = useAuthStore((s) => s.setInitialized)

  useEffect(() => {
    api.get('/auth/me')
      .then((r) => setUser(r.data))
      .catch((err) => {
        // 401 = expected "no valid session" — route guards redirect
        // to /login and the HttpOnly cookie is cleared on next login
        // or logout. Anything else (5xx, network failure) is a real
        // problem we want to surface in the console rather than
        // pretending the user is logged out.
        if (err?.response?.status !== 401) {
          console.error('AppInit /auth/me failed:', err)
        }
      })
      .finally(() => setInitialized(true))
  }, [setUser, setInitialized])

  return <>{children}</>
}
