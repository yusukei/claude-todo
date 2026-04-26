/**
 * ConfirmDialog — promise resolves on confirm / cancel / ESC / backdrop.
 *
 * The imperative ``showConfirm`` is used by every destructive mutation
 * (delete document, delete task, etc.). A bug that resolves the promise
 * before the user clicked is a silent data-loss class issue.
 */
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ConfirmDialog, { showConfirm } from '../../components/common/ConfirmDialog'

describe('ConfirmDialog — initial state', () => {
  it('renders nothing while no confirm is pending', () => {
    const { container } = render(<ConfirmDialog />)
    expect(container.firstChild).toBeNull()
  })
})

describe('ConfirmDialog — promise resolves on confirm', () => {
  it('clicking 実行 resolves the promise with true and closes', async () => {
    const user = userEvent.setup()
    render(<ConfirmDialog />)
    const result = vi.fn()
    act(() => {
      void showConfirm('本当にやりますか？').then(result)
    })
    expect(screen.getByText('本当にやりますか？')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '実行' }))
    await Promise.resolve()
    expect(result).toHaveBeenCalledWith(true)
    expect(screen.queryByText('本当にやりますか？')).toBeNull()
  })
})

describe('ConfirmDialog — promise resolves on cancel', () => {
  it('clicking キャンセル resolves the promise with false', async () => {
    const user = userEvent.setup()
    render(<ConfirmDialog />)
    const result = vi.fn()
    act(() => {
      void showConfirm('cancel me').then(result)
    })
    await user.click(screen.getByRole('button', { name: 'キャンセル' }))
    await Promise.resolve()
    expect(result).toHaveBeenCalledWith(false)
    expect(screen.queryByText('cancel me')).toBeNull()
  })
})

describe('ConfirmDialog — ESC key cancels', () => {
  it('pressing Escape resolves with false', async () => {
    render(<ConfirmDialog />)
    const result = vi.fn()
    act(() => {
      void showConfirm('escape me').then(result)
    })
    fireEvent.keyDown(document, { key: 'Escape' })
    await Promise.resolve()
    expect(result).toHaveBeenCalledWith(false)
    expect(screen.queryByText('escape me')).toBeNull()
  })
})

describe('ConfirmDialog — backdrop click cancels', () => {
  it('clicking the dimmed backdrop resolves with false', async () => {
    render(<ConfirmDialog />)
    const result = vi.fn()
    act(() => {
      void showConfirm('backdrop me').then(result)
    })
    // The backdrop is the absolute fill behind the modal panel.
    const backdrop = document.querySelector('.bg-black\\/50') as HTMLElement
    expect(backdrop).not.toBeNull()
    fireEvent.click(backdrop)
    await Promise.resolve()
    expect(result).toHaveBeenCalledWith(false)
    expect(screen.queryByText('backdrop me')).toBeNull()
  })
})
