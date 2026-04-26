/**
 * LiveActivityPanel — toggle + list rendering.
 */
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import LiveActivityPanel from '../../components/common/LiveActivityPanel'
import { server } from '../mocks/server'
import { useAuthStore } from '../../store/auth'
import { createMockUser } from '../mocks/factories'
import { renderWithProviders } from '../utils/renderWithProviders'

beforeEach(() => {
  useAuthStore.setState({ user: createMockUser(), isInitialized: true })
})

describe('LiveActivityPanel — closed by default', () => {
  it('shows only the toggle button when no panel has been opened', async () => {
    server.use(
      http.get(/\/api\/v1\/tasks\/live/, () => HttpResponse.json([])),
    )
    renderWithProviders(<LiveActivityPanel />)
    // Toggle is an Activity-icon button — accept either role match
    // or an aria-labelled button.
    const buttons = screen.getAllByRole('button')
    expect(buttons.length).toBeGreaterThan(0)
    // The list panel content is not yet on screen.
    expect(screen.queryByText(/in-progress|running|進行中/i)).toBeNull()
  })
})

describe('LiveActivityPanel — opens to show in-progress tasks', () => {
  it('renders the task title + project name once the panel is open', async () => {
    server.use(
      http.get(/\/api\/v1\/tasks\/live/, () =>
        HttpResponse.json([
          {
            id: 't-1',
            title: 'BUILD-BUNDLE-XYZ',
            active_form: 'Building bundle now',
            assignee_id: null,
            project_id: 'p-1',
            project_name: 'AlphaProj',
            updated_at: new Date().toISOString(),
            created_at: new Date().toISOString(),
          },
        ]),
      ),
    )
    const user = userEvent.setup()
    renderWithProviders(<LiveActivityPanel />)
    // The toggle's title attribute contains "ライブアクティビティ".
    const toggle = await waitFor(() =>
      document.querySelector('[title*="ライブアクティビティ"]') as HTMLElement,
    )
    expect(toggle).not.toBeNull()
    await user.click(toggle)
    // The panel renders an anchor element containing both task title
    // and project name. Search via document.body.textContent for
    // robustness against intermediate layout wrappers.
    await waitFor(() => {
      expect(document.body.textContent).toContain('BUILD-BUNDLE-XYZ')
      expect(document.body.textContent).toContain('AlphaProj')
    })
  })
})
