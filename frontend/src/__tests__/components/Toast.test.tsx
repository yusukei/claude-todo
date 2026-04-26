/**
 * Toast — show / auto-dismiss / manual dismiss / type variants.
 *
 * Toast is a global imperative API used by every mutation across
 * the app. A regression here is silently invisible (no error toast
 * means the user thinks the failed action succeeded).
 */
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ToastContainer, {
  showErrorToast,
  showInfoToast,
  showSuccessToast,
} from '../../components/common/Toast'

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
})

describe('Toast — show / type variants', () => {
  it('renders nothing when no toast has been queued', () => {
    const { container } = render(<ToastContainer />)
    expect(container.firstChild).toBeNull()
  })

  it('shows the message text after showInfoToast', () => {
    render(<ToastContainer />)
    act(() => {
      showInfoToast('hello info')
    })
    expect(screen.getByText('hello info')).toBeInTheDocument()
  })

  it('shows multiple toasts simultaneously', () => {
    render(<ToastContainer />)
    act(() => {
      showInfoToast('first')
      showSuccessToast('second')
      showErrorToast('third')
    })
    expect(screen.getByText('first')).toBeInTheDocument()
    expect(screen.getByText('second')).toBeInTheDocument()
    expect(screen.getByText('third')).toBeInTheDocument()
  })
})

describe('Toast — auto dismiss timing differs by type', () => {
  it('non-error toasts dismiss after 4 seconds', () => {
    render(<ToastContainer />)
    act(() => {
      showInfoToast('temp info')
    })
    expect(screen.queryByText('temp info')).not.toBeNull()
    // Just before 4s — still visible.
    act(() => {
      vi.advanceTimersByTime(3500)
    })
    expect(screen.queryByText('temp info')).not.toBeNull()
    // Past 4s + the 200ms exit animation.
    act(() => {
      vi.advanceTimersByTime(700)
    })
    expect(screen.queryByText('temp info')).toBeNull()
  })

  it('error toasts persist 8 seconds (twice as long)', () => {
    render(<ToastContainer />)
    act(() => {
      showErrorToast('something broke')
    })
    act(() => {
      vi.advanceTimersByTime(4500)
    })
    // Info would already be gone here — error must still be present.
    expect(screen.queryByText('something broke')).not.toBeNull()
    act(() => {
      vi.advanceTimersByTime(4000)
    })
    expect(screen.queryByText('something broke')).toBeNull()
  })
})

describe('Toast — manual dismiss', () => {
  it('clicking the close button removes the toast immediately', async () => {
    vi.useRealTimers()
    const user = userEvent.setup()
    render(<ToastContainer />)
    act(() => {
      showInfoToast('dismiss me')
    })
    const closeBtn = await screen.findByLabelText('閉じる')
    await user.click(closeBtn)
    // After the 200ms close animation, the toast should be removed.
    await new Promise<void>((r) => setTimeout(r, 250))
    expect(screen.queryByText('dismiss me')).toBeNull()
  })
})
