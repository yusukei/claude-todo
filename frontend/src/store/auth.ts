import { create } from 'zustand'
import type { User } from '../types'

interface AuthState {
  user: User | null
  isInitialized: boolean
  setUser: (user: User | null) => void
  setInitialized: (v: boolean) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isInitialized: false,
  setUser: (user) => set({ user }),
  setInitialized: (isInitialized) => set({ isInitialized }),
  logout: () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    set({ user: null })
  },
}))
