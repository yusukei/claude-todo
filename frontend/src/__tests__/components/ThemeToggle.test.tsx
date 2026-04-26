/**
 * ThemeToggle + theme store — light / dark / system mode persistence.
 */
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ThemeToggle from '../../components/common/ThemeToggle'
import { useThemeStore } from '../../store/theme'

const STORAGE_KEY = 'theme_mode'

beforeEach(() => {
  // Force-reset to a known state — the store reads from localStorage
  // at module load, but tests should not leak between runs.
  window.localStorage.removeItem(STORAGE_KEY)
  document.documentElement.classList.remove('dark')
  act(() => {
    useThemeStore.setState({ mode: 'system' })
  })
})

afterEach(() => {
  window.localStorage.removeItem(STORAGE_KEY)
})

describe('ThemeToggle — render', () => {
  it('shows three mode buttons (light / dark / system)', () => {
    render(<ThemeToggle />)
    expect(screen.getByLabelText('ライトモードに切り替え')).toBeInTheDocument()
    expect(screen.getByLabelText('ダークモードに切り替え')).toBeInTheDocument()
    expect(screen.getByLabelText('システムモードに切り替え')).toBeInTheDocument()
  })
})

describe('ThemeToggle — clicking dark sets the mode + persists + adds .dark class', () => {
  it('updates store, localStorage, and the html class', async () => {
    const user = userEvent.setup()
    render(<ThemeToggle />)
    await user.click(screen.getByLabelText('ダークモードに切り替え'))
    expect(useThemeStore.getState().mode).toBe('dark')
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
  })
})

describe('ThemeToggle — clicking light removes the .dark class', () => {
  it('persists "light" and clears the html dark class', async () => {
    const user = userEvent.setup()
    // Pre-condition: start in dark mode.
    act(() => {
      useThemeStore.getState().setMode('dark')
    })
    expect(document.documentElement.classList.contains('dark')).toBe(true)

    render(<ThemeToggle />)
    await user.click(screen.getByLabelText('ライトモードに切り替え'))
    expect(useThemeStore.getState().mode).toBe('light')
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('light')
    expect(document.documentElement.classList.contains('dark')).toBe(false)
  })
})

describe('ThemeToggle — system mode follows matchMedia', () => {
  it('persists "system" and applies dark when prefers-color-scheme is dark', async () => {
    const user = userEvent.setup()
    // Stub matchMedia to report dark preference.
    const original = window.matchMedia
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: vi.fn().mockReturnValue({
        matches: true,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }),
    })
    render(<ThemeToggle />)
    await user.click(screen.getByLabelText('システムモードに切り替え'))
    expect(useThemeStore.getState().mode).toBe('system')
    expect(window.localStorage.getItem(STORAGE_KEY)).toBe('system')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      value: original,
    })
  })
})
