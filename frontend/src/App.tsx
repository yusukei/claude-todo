import React, { Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ErrorBoundary from './components/common/ErrorBoundary'
import { useGlobalErrorHandler } from './hooks/useGlobalErrorHandler'
import Layout from './components/common/Layout'
import AppInit from './components/common/AppInit'
import ToastContainer from './components/common/Toast'
import ConfirmDialog from './components/common/ConfirmDialog'
import ProtectedRoute from './components/common/ProtectedRoute'
import AdminRoute from './components/common/AdminRoute'
import LoginPage from './pages/LoginPage'
import ProjectsPage from './pages/ProjectsPage'
import ProjectSettingsPage from './pages/ProjectSettingsPage'
import DocumentPage from './pages/DocumentPage'
import DocSitesPage from './pages/DocSitesPage'
import SettingsPage from './pages/SettingsPage'

// Heavy pages (>15KB) — code-split to keep the initial bundle small.
// LoadingFallback inside the route element below covers the suspense boundary.
// WorkbenchPage is the body of `/projects/:projectId` since Phase C2 D3.
// (The legacy ProjectPage was deleted in the same commit; previously the
//  Workbench had its own `/workbench/:projectId` route gated by a dev flag.)
// Phase 1 (Lifecycle & Ownership 仕様書 §3.1): WorkbenchShell が永続的な
// 親として WorkbenchPage を常時 mount する (settings / documents は
// overlay として子ルートで表示)。これにより project 内のページ遷移で
// TerminalView の WebSocket が切断されなくなる。
const WorkbenchShell = React.lazy(() => import('./pages/WorkbenchShell'))
const KnowledgePage = React.lazy(() => import('./pages/KnowledgePage'))
const DocSiteViewerPage = React.lazy(() => import('./pages/DocSiteViewerPage'))
const TerminalPage = React.lazy(() => import('./pages/TerminalPage'))
const BookmarksPage = React.lazy(() => import('./pages/BookmarksPage'))
const GoogleCallbackPage = React.lazy(() => import('./pages/GoogleCallbackPage'))
const AdminPage = React.lazy(() => import('./pages/AdminPage'))
const UserDetailPage = React.lazy(() => import('./pages/admin/UserDetailPage'))
const NotFoundPage = React.lazy(() => import('./pages/NotFoundPage'))

// Phase 1.5: design-system preview. Enabled when either:
//   * vite is running in DEV mode (``npm run dev``), or
//   * the build defines ``VITE_DEV_PREVIEW=1`` (set on staging so we
//     can eyeball Phase 2-6 progress without spinning up local dev).
// Pure-production builds keep the gate ``false`` so Rollup tree-shakes
// the lazy import out of ``dist/``.
const DEV_PREVIEW_ENABLED =
  import.meta.env.DEV || import.meta.env.VITE_DEV_PREVIEW === '1'
const DevPreviewPage = DEV_PREVIEW_ENABLED
  ? React.lazy(() => import('./pages/dev/DevPreviewPage'))
  : null

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
})

const LoadingFallback = () => (
  <div className="flex items-center justify-center h-screen text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-900" role="status" aria-live="polite">読み込み中...</div>
)

// Wrap a lazily-loaded element in Suspense — keeps the JSX below tidy.
const lazy = (node: React.ReactNode) => (
  <Suspense fallback={<LoadingFallback />}>{node}</Suspense>
)

/**
 * Phase 1 (Lifecycle & Ownership 仕様書 §3.1): ErrorBoundary の key を
 * project スコープに丸める。`location.pathname` をそのまま key にすると
 * project 内のルート遷移 (workbench → settings → workbench) で毎回
 * ErrorBoundary が remount され、配下の WorkbenchShell / WorkbenchPage /
 * TerminalView の WS まで巻き添えで unmount される。`/projects/:projectId/*`
 * は同じ key に集約することで project 内遷移で remount しなくなる。
 * project 切替 (A → B) では key が変わるので従来どおり remount する
 * (Phase 2 で更に改善予定)。
 */
function makeBoundaryKey(pathname: string): string {
  const m = pathname.match(/^\/projects\/([^/]+)/)
  if (m) return `/projects/${m[1]}`
  return pathname
}

function AppRoutes() {
  const location = useLocation()
  useGlobalErrorHandler()
  return (
    <ErrorBoundary key={makeBoundaryKey(location.pathname)}>
      <AppInit>
        <ToastContainer />
        <ConfirmDialog />
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/auth/google/callback" element={lazy(<GoogleCallbackPage />)} />
          <Route
            path="/"
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="/projects" replace />} />
            <Route path="projects" element={<ProjectsPage />} />
            <Route path="projects/:projectId" element={lazy(<WorkbenchShell />)}>
              <Route path="settings" element={<ProjectSettingsPage />} />
              <Route path="documents/:documentId" element={<DocumentPage />} />
            </Route>


            <Route path="knowledge" element={lazy(<KnowledgePage />)} />
            <Route path="knowledge/:knowledgeId" element={lazy(<KnowledgePage />)} />
            <Route path="docsites" element={<DocSitesPage />} />
            <Route path="docsites/:siteId/*" element={lazy(<DocSiteViewerPage />)} />
            <Route path="bookmarks" element={lazy(<BookmarksPage />)} />
            <Route path="bookmarks/:bookmarkId" element={lazy(<BookmarksPage />)} />
            <Route path="workspaces" element={<Navigate to="/admin" replace />} />
            <Route
              path="workspaces/terminal/:agentId"
              element={
                <AdminRoute>
                  {lazy(<TerminalPage />)}
                </AdminRoute>
              }
            />
            <Route
              path="workspaces/terminal/:agentId/:sessionId"
              element={
                <AdminRoute>
                  {lazy(<TerminalPage />)}
                </AdminRoute>
              }
            />
            <Route path="settings" element={<SettingsPage />} />
            <Route
              path="admin"
              element={
                <AdminRoute>
                  {lazy(<AdminPage />)}
                </AdminRoute>
              }
            />
            <Route
              path="admin/users/:userId"
              element={
                <AdminRoute>
                  {lazy(<UserDetailPage />)}
                </AdminRoute>
              }
            />
          </Route>
          {/* Phase 1.5: dev-only design-system preview. Rendered outside
              the ProtectedRoute so it works without auth in local dev.
              Production builds drop the route via the DEV gate. */}
          {DevPreviewPage && (
            <Route path="/dev/preview" element={lazy(<DevPreviewPage />)} />
          )}
          <Route path="*" element={lazy(<NotFoundPage />)} />
        </Routes>
      </AppInit>
    </ErrorBoundary>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
