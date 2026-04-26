/**
 * MarkdownRenderer — happy path + edge cases.
 *
 * Renderer is used by every doc / task description / clip preview.
 * We don't try to assert against react-markdown's HTML structure
 * (brittle); instead we verify text survives the round-trip and
 * that the component doesn't crash on the empty/undefined cases
 * that have bitten us before.
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import MarkdownRenderer from '../../components/common/MarkdownRenderer'

// mermaid.render is async-only and not relevant here — tests
// assert text rendering, not diagram rendering.
vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn().mockResolvedValue({ svg: '' }),
  },
}))

describe('MarkdownRenderer — text content', () => {
  it('renders plain text inside the body', () => {
    render(<MarkdownRenderer>Hello world</MarkdownRenderer>)
    expect(screen.getByText('Hello world')).toBeInTheDocument()
  })

  it('renders an h1 from a Markdown heading', () => {
    const { container } = render(<MarkdownRenderer># Big title</MarkdownRenderer>)
    expect(container.querySelector('h1')?.textContent).toBe('Big title')
  })

  it('renders a list', () => {
    const { container } = render(
      <MarkdownRenderer>{'- one\n- two\n- three'}</MarkdownRenderer>,
    )
    const items = container.querySelectorAll('li')
    expect(items.length).toBe(3)
  })
})

describe('MarkdownRenderer — does not crash on empty / whitespace input', () => {
  it('empty string', () => {
    expect(() => render(<MarkdownRenderer>{''}</MarkdownRenderer>)).not.toThrow()
  })
  it('only whitespace', () => {
    expect(() => render(<MarkdownRenderer>{'   \n\n  '}</MarkdownRenderer>)).not.toThrow()
  })
})
