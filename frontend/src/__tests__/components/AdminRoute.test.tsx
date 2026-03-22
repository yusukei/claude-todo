import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import AdminRoute from '../../components/common/AdminRoute'
import { useAuthStore } from '../../store/auth'

function renderWithRouter(ui: React.ReactNode, initialPath = '/admin') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/admin" element={ui} />
        <Route path="/login" element={<div>Login Page</div>} />
        <Route path="/projects" element={<div>Projects Page</div>} />
      </Routes>
    </MemoryRouter>
  )
}

describe('AdminRoute', () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null })
    localStorage.clear()
  })

  it('user が admin の場合 children を描画', () => {
    useAuthStore.setState({
      user: {
        id: '1',
        email: 'admin@test.com',
        name: 'Admin',
        is_admin: true,
        auth_type: 'admin',
        is_active: true,
        created_at: '2024-01-01T00:00:00Z',
      },
    })

    renderWithRouter(
      <AdminRoute>
        <div>Admin Content</div>
      </AdminRoute>
    )
    expect(screen.getByText('Admin Content')).toBeInTheDocument()
  })

  it('user が admin でない場合 /projects にリダイレクト', () => {
    useAuthStore.setState({
      user: {
        id: '2',
        email: 'user@test.com',
        name: 'Regular',
        is_admin: false,
        auth_type: 'google',
        is_active: true,
        created_at: '2024-01-01T00:00:00Z',
      },
    })

    renderWithRouter(
      <AdminRoute>
        <div>Admin Content</div>
      </AdminRoute>
    )
    expect(screen.getByText('Projects Page')).toBeInTheDocument()
    expect(screen.queryByText('Admin Content')).not.toBeInTheDocument()
  })

  it('user が null の場合 /login にリダイレクト', () => {
    renderWithRouter(
      <AdminRoute>
        <div>Admin Content</div>
      </AdminRoute>
    )
    expect(screen.getByText('Login Page')).toBeInTheDocument()
    expect(screen.queryByText('Admin Content')).not.toBeInTheDocument()
  })
})
