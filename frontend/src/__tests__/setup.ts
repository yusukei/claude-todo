import '@testing-library/jest-dom'
import { afterAll, afterEach, beforeAll, vi } from 'vitest'
import { server } from './mocks/server'

// react-tweet imports .module.css files that jsdom cannot process
vi.mock('react-tweet', () => ({ Tweet: () => null }))

// jsdom does not implement EventSource. `useSSE` instantiates one in
// connect() — without this stub, any test that mounts a component using
// useSSE produces an unhandled `ReferenceError: EventSource is not defined`
// rejection, which fails the whole vitest run even when every test passes.
// The stub is intentionally inert: connect()'s side effects (CONNECTED state,
// invalidateQueries, etc.) are not exercised by these tests.
class MockEventSource {
  url: string
  readyState = 0
  onopen: ((ev?: unknown) => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onerror: ((ev?: unknown) => void) | null = null
  constructor(url: string) {
    this.url = url
  }
  addEventListener() {}
  removeEventListener() {}
  close() {}
}
if (typeof globalThis.EventSource === 'undefined') {
  ;(globalThis as { EventSource?: unknown }).EventSource = MockEventSource
}

// MSW サーバーをテストスイート全体で起動
beforeAll(() => server.listen({ onUnhandledRequest: 'warn' }))
afterEach(() => {
  server.resetHandlers() // テスト間でハンドラーをリセット
  localStorage.clear()   // localStorage をクリア
})
afterAll(() => server.close())
