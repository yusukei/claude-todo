import '@testing-library/jest-dom'
import { afterAll, afterEach, beforeAll, vi } from 'vitest'
import { server } from './mocks/server'

// react-tweet imports .module.css files that jsdom cannot process
vi.mock('react-tweet', () => ({ Tweet: () => null }))

// MSW サーバーをテストスイート全体で起動
beforeAll(() => server.listen({ onUnhandledRequest: 'warn' }))
afterEach(() => {
  server.resetHandlers() // テスト間でハンドラーをリセット
  localStorage.clear()   // localStorage をクリア
})
afterAll(() => server.close())
