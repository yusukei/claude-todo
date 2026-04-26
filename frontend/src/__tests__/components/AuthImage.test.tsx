/**
 * AuthImage — internal /api/* paths fetch via the api client and
 * render a blob URL; external paths fall through to a plain img;
 * missing src renders nothing.
 */
import { describe, expect, it, vi } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import AuthImage from '../../components/common/AuthImage'

vi.mock('../../api/client', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ data: new Blob(['fake-png-bytes']) }),
  },
}))

describe('AuthImage — external src', () => {
  it('renders a plain <img> for non-/api/ src values', () => {
    const { container } = render(
      <AuthImage src="https://example.com/x.png" alt="x" />,
    )
    const img = container.querySelector('img')
    expect(img).not.toBeNull()
    expect(img!.getAttribute('src')).toBe('https://example.com/x.png')
  })
})

describe('AuthImage — internal src', () => {
  it('shows a placeholder until the blob resolves, then swaps to the blob URL', async () => {
    // jsdom needs URL.createObjectURL.
    const original = URL.createObjectURL
    URL.createObjectURL = vi.fn(() => 'blob:fake')
    try {
      const { container } = render(
        <AuthImage src="/api/v1/projects/x/attachments/y.png" alt="y" />,
      )
      // Loading placeholder while fetch is pending — no <img> yet.
      expect(container.querySelector('img')).toBeNull()
      await waitFor(() => {
        const img = container.querySelector('img')
        expect(img).not.toBeNull()
        expect(img!.getAttribute('src')).toBe('blob:fake')
      })
    } finally {
      URL.createObjectURL = original
    }
  })
})

describe('AuthImage — missing src', () => {
  it('renders nothing when src is undefined', () => {
    const { container } = render(<AuthImage alt="ghost" />)
    expect(container.firstChild).toBeNull()
  })
})
