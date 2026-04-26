/**
 * AgentRegisterDialog — open/close + name validation + token reveal.
 */
import { describe, expect, it, vi } from 'vitest'
import { http, HttpResponse } from 'msw'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AgentRegisterDialog from '../../components/workspace/AgentRegisterDialog'
import { server } from '../mocks/server'

describe('AgentRegisterDialog — closed state', () => {
  it('renders nothing when open=false', () => {
    const { container } = render(
      <AgentRegisterDialog open={false} onClose={vi.fn()} onCreated={vi.fn()} />,
    )
    expect(container.firstChild).toBeNull()
  })
})

describe('AgentRegisterDialog — happy path', () => {
  it('POST /workspaces/agents on submit and exposes the issued token', async () => {
    server.use(
      http.post('/api/v1/workspaces/agents', () =>
        HttpResponse.json({ token: 'BEARER-XYZ-123', id: 'a-1' }),
      ),
    )
    const user = userEvent.setup()
    const onCreated = vi.fn()
    render(
      <AgentRegisterDialog open onClose={vi.fn()} onCreated={onCreated} />,
    )
    // Find the name input by placeholder, label, or fallback.
    const nameInput =
      screen.queryByPlaceholderText(/名前|name/i) ??
      screen.queryByLabelText(/名前|name/i) ??
      (document.querySelector('input[type="text"]') as HTMLInputElement | null)
    expect(nameInput).not.toBeNull()
    await user.type(nameInput as HTMLInputElement, 'Workstation A')
    // Submit button — accept Japanese/English variants.
    const submit =
      screen.queryByRole('button', { name: /登録|register|create|作成|送信/i }) ??
      screen.queryByText(/登録|register/i)
    expect(submit).not.toBeNull()
    await user.click(submit as HTMLElement)
    await waitFor(() => {
      expect(onCreated).toHaveBeenCalledTimes(1)
    })
    // The newly issued token must be visible somewhere in the dialog
    // so the user can copy it.
    await waitFor(() => {
      expect(document.body.textContent).toContain('BEARER-XYZ-123')
    })
  })
})
