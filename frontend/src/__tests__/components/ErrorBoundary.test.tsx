/**
 * ErrorBoundary — catches render-time errors, shows fallback UI,
 * and lets the user trigger a reload. PageErrorFallback is the
 * compact in-layout variant.
 */
import { describe, expect, it, vi, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import ErrorBoundary, {
  PageErrorFallback,
} from '../../components/common/ErrorBoundary'

function Boom(): JSX.Element {
  throw new Error('intentional render error')
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ErrorBoundary — happy path', () => {
  it('renders children when nothing throws', () => {
    render(
      <ErrorBoundary>
        <div data-testid="child">OK</div>
      </ErrorBoundary>,
    )
    expect(screen.getByTestId('child')).toBeInTheDocument()
  })
})

describe('ErrorBoundary — catches render errors', () => {
  it('shows the default fallback UI when a child throws', () => {
    // Suppress the console.error noise React emits for caught errors.
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )
    expect(
      screen.getByText('予期しないエラーが発生しました'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'ページを再読み込み' }),
    ).toBeInTheDocument()
  })
})

describe('ErrorBoundary — custom fallback prop', () => {
  it('renders the supplied fallback instead of the default UI', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <ErrorBoundary fallback={<div data-testid="custom-fallback">CUSTOM</div>}>
        <Boom />
      </ErrorBoundary>,
    )
    expect(screen.getByTestId('custom-fallback')).toBeInTheDocument()
    expect(
      screen.queryByText('予期しないエラーが発生しました'),
    ).toBeNull()
  })
})

describe('PageErrorFallback', () => {
  it('renders a compact reload prompt', () => {
    render(<PageErrorFallback />)
    expect(
      screen.getByText(
        'このページの読み込み中にエラーが発生しました',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: '再読み込み' }),
    ).toBeInTheDocument()
  })
})
