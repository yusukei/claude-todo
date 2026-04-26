/**
 * Domain API client wrappers — URL composition + body / params shape.
 *
 * These wrappers are thin: their value is consistent URL composition
 * across pages (no `/projects/${id}` typos buried in feature code).
 * The test asserts that each method hits the expected method+path
 * with the expected body/params; payload shape on the wire is
 * the contract the rest of the app builds on.
 */
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '../mocks/server'
import { bookmarksApi, bookmarkCollectionsApi } from '../../api/bookmarks'
import { knowledgeApi } from '../../api/knowledge'
import { projectsApi } from '../../api/projects'
import { secretsApi } from '../../api/secrets'
import { tasksApi } from '../../api/tasks'
import { errorTrackerApi, usersApi } from '../../api/errorTracker'

interface Captured {
  method: string
  path: string
  search: string
  body?: unknown
}

/**
 * Helper that registers a one-shot handler matching `path`, captures
 * the inbound request, and returns a JSON response.
 */
function captureRoute(
  method: 'get' | 'post' | 'put' | 'patch' | 'delete',
  path: string,
  responseBody: unknown,
  out: { current: Captured | null },
) {
  server.use(
    (http as unknown as Record<string, (path: string, resolver: (r: { request: Request }) => Response) => unknown>)[method](
      `/api/v1${path}`,
      async ({ request }) => {
        const url = new URL(request.url)
        const body =
          method === 'post' || method === 'put' || method === 'patch'
            ? await request.clone().json().catch(() => undefined)
            : undefined
        out.current = {
          method: method.toUpperCase(),
          path: url.pathname,
          search: url.search,
          body,
        }
        return HttpResponse.json(responseBody) as unknown as Response
      },
    ),
  )
}

describe('bookmarksApi — URL composition', () => {
  it('list passes collection_id / limit / skip as query params', async () => {
    const out = { current: null as Captured | null }
    captureRoute('get', '/bookmarks', [], out)
    await bookmarksApi.list({ collection_id: 'c1', limit: 5, skip: 10 })
    expect(out.current?.path).toBe('/api/v1/bookmarks')
    expect(out.current?.search).toContain('collection_id=c1')
    expect(out.current?.search).toContain('limit=5')
    expect(out.current?.search).toContain('skip=10')
  })

  it('get includes the id in the path', async () => {
    const out = { current: null as Captured | null }
    captureRoute('get', '/bookmarks/abc-123', { id: 'abc-123' }, out)
    const r = await bookmarksApi.get('abc-123')
    expect(r).toEqual({ id: 'abc-123' })
    expect(out.current?.path).toBe('/api/v1/bookmarks/abc-123')
  })

  it('create POSTs the data body', async () => {
    const out = { current: null as Captured | null }
    captureRoute('post', '/bookmarks', { id: 'new' }, out)
    await bookmarksApi.create({ url: 'https://e.x', collection_id: 'c1', title: 't' })
    expect(out.current?.body).toEqual({
      url: 'https://e.x',
      collection_id: 'c1',
      title: 't',
    })
  })

  it('search hits /bookmarks/search with q', async () => {
    const out = { current: null as Captured | null }
    captureRoute('get', '/bookmarks/search', [], out)
    await bookmarksApi.search('react')
    expect(out.current?.search).toContain('q=react')
  })
})

describe('bookmarkCollectionsApi — URL composition', () => {
  it('list / get / create / update / remove all hit /bookmark-collections', async () => {
    const out = { current: null as Captured | null }
    captureRoute('get', '/bookmark-collections', [], out)
    await bookmarkCollectionsApi.list()
    expect(out.current?.path).toBe('/api/v1/bookmark-collections')

    captureRoute('get', '/bookmark-collections/c1', {}, out)
    await bookmarkCollectionsApi.get('c1')
    expect(out.current?.path).toBe('/api/v1/bookmark-collections/c1')

    captureRoute('post', '/bookmark-collections', {}, out)
    await bookmarkCollectionsApi.create({ name: 'New' })
    expect(out.current?.body).toEqual({ name: 'New' })

    captureRoute('patch', '/bookmark-collections/c1', {}, out)
    await bookmarkCollectionsApi.update('c1', { name: 'X' })
    expect(out.current?.body).toEqual({ name: 'X' })

    captureRoute('delete', '/bookmark-collections/c1', {}, out)
    await bookmarkCollectionsApi.remove('c1')
    expect(out.current?.method).toBe('DELETE')
  })
})

describe('knowledgeApi — URL composition', () => {
  it('list / get / search compose the right paths', async () => {
    const out = { current: null as Captured | null }
    captureRoute('get', '/knowledge', [], out)
    await knowledgeApi.list({ category: 'pattern', limit: 10 })
    expect(out.current?.search).toContain('category=pattern')
    expect(out.current?.search).toContain('limit=10')

    captureRoute('get', '/knowledge/k1', { id: 'k1' }, out)
    await knowledgeApi.get('k1')
    expect(out.current?.path).toBe('/api/v1/knowledge/k1')

    captureRoute('get', '/knowledge/search', [], out)
    await knowledgeApi.search('foo', { limit: 5 })
    expect(out.current?.search).toContain('q=foo')
    expect(out.current?.search).toContain('limit=5')
  })
})

describe('projectsApi — URL composition', () => {
  it('CRUD + summary + reorder', async () => {
    const out = { current: null as Captured | null }
    captureRoute('get', '/projects', [], out)
    await projectsApi.list()
    expect(out.current?.path).toBe('/api/v1/projects')

    captureRoute('get', '/projects/p1', {}, out)
    await projectsApi.get('p1')
    expect(out.current?.path).toBe('/api/v1/projects/p1')

    captureRoute('get', '/projects/p1/summary', {}, out)
    await projectsApi.summary('p1')
    expect(out.current?.path).toBe('/api/v1/projects/p1/summary')

    captureRoute('post', '/projects/reorder', {}, out)
    await projectsApi.reorder(['a', 'b'])
    expect(out.current?.body).toEqual({ ids: ['a', 'b'] })
  })
})

describe('secretsApi — URL composition', () => {
  it('all routes nest under /projects/:id/secrets/', async () => {
    const out = { current: null as Captured | null }
    captureRoute('get', '/projects/p1/secrets/', [], out)
    await secretsApi.list('p1', { limit: 20 })
    expect(out.current?.path).toBe('/api/v1/projects/p1/secrets/')
    expect(out.current?.search).toContain('limit=20')

    captureRoute('post', '/projects/p1/secrets/', {}, out)
    await secretsApi.create('p1', { key: 'GITHUB_TOKEN', value: 'gha' })
    expect(out.current?.body).toEqual({ key: 'GITHUB_TOKEN', value: 'gha' })

    captureRoute('put', '/projects/p1/secrets/GITHUB_TOKEN', {}, out)
    await secretsApi.update('p1', 'GITHUB_TOKEN', { value: 'rotated' })
    expect(out.current?.method).toBe('PUT')

    captureRoute('delete', '/projects/p1/secrets/GITHUB_TOKEN', {}, out)
    await secretsApi.remove('p1', 'GITHUB_TOKEN')
    expect(out.current?.method).toBe('DELETE')

    captureRoute('get', '/projects/p1/secrets/GITHUB_TOKEN/value', { value: 'gha' }, out)
    const v = await secretsApi.getValue('p1', 'GITHUB_TOKEN')
    expect(v).toEqual({ value: 'gha' })
  })
})

describe('tasksApi — URL composition', () => {
  it('list passes filters, archive/unarchive POST the right paths', async () => {
    const out = { current: null as Captured | null }
    captureRoute('get', '/tasks', { items: [], total: 0, limit: 50, skip: 0 }, out)
    await tasksApi.list({ project_id: 'p1', status: 'todo', archived: false })
    expect(out.current?.search).toContain('project_id=p1')
    expect(out.current?.search).toContain('status=todo')
    expect(out.current?.search).toContain('archived=false')

    captureRoute('post', '/tasks/t1/archive', {}, out)
    await tasksApi.archive('t1')
    expect(out.current?.method).toBe('POST')
    expect(out.current?.path).toBe('/api/v1/tasks/t1/archive')

    captureRoute('post', '/tasks/t1/comments', {}, out)
    await tasksApi.addComment('t1', 'hello')
    expect(out.current?.body).toEqual({ content: 'hello' })

    captureRoute('delete', '/tasks/t1/comments/c1', {}, out)
    await tasksApi.deleteComment('t1', 'c1')
    expect(out.current?.method).toBe('DELETE')
    expect(out.current?.path).toBe('/api/v1/tasks/t1/comments/c1')
  })
})

describe('errorTrackerApi — URL composition', () => {
  it('listProjects / listIssues / resolve / ignore / reopen / histogram', async () => {
    const out = { current: null as Captured | null }
    captureRoute('get', '/error-tracker/projects', [], out)
    await errorTrackerApi.listProjects()
    expect(out.current?.path).toBe('/api/v1/error-tracker/projects')

    captureRoute('get', '/error-tracker/projects/ep1/issues', [], out)
    await errorTrackerApi.listIssues('ep1', { status: 'unresolved', limit: 10 })
    expect(out.current?.search).toContain('status=unresolved')
    expect(out.current?.search).toContain('limit=10')

    captureRoute('post', '/error-tracker/issues/i1/resolve', {}, out)
    await errorTrackerApi.resolve('i1', 'fixed in deploy')
    expect(out.current?.body).toEqual({ resolution: 'fixed in deploy' })

    captureRoute('post', '/error-tracker/issues/i1/ignore', {}, out)
    await errorTrackerApi.ignore('i1', '2026-12-31')
    expect(out.current?.body).toEqual({ until: '2026-12-31' })

    captureRoute('post', '/error-tracker/issues/i1/reopen', {}, out)
    await errorTrackerApi.reopen('i1')
    expect(out.current?.method).toBe('POST')

    captureRoute('get', '/error-tracker/issues/i1/histogram', [], out)
    await errorTrackerApi.histogram('i1', '7d', '1d')
    expect(out.current?.search).toContain('period=7d')
    expect(out.current?.search).toContain('interval=1d')
  })
})

describe('usersApi.searchActive', () => {
  it('passes q + limit', async () => {
    const out = { current: null as Captured | null }
    captureRoute('get', '/users/search/active', [], out)
    await usersApi.searchActive('alice', 5)
    expect(out.current?.search).toContain('q=alice')
    expect(out.current?.search).toContain('limit=5')
  })
})
