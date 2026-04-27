/**
 * URL Contract — TypeScript ``buildUrl`` / ``parseUrl`` (URL S5).
 *
 * 仕様書: ``docs/api/url-contract.md``
 * 共有 fixture: ``docs/api/url-contract.fixtures.json``
 *
 * Backend ``backend/app/lib/url_contract.py`` と **完全に同じスキーマ** を
 * 実装する。CI で fixture を両側から読むことで round-trip 不変条件
 * (URL-1) を保証。
 *
 * 本モジュールはサーバ通信を一切しない pure 関数の集合。``CopyUrlButton``
 * (URL S6) と Workbench の URL writeback (Phase 2 既存) が import する。
 *
 * 既存の ``frontend/src/workbench/urlContract.ts`` (Phase C2 D3) は別物
 * (Workbench 内部の query 解釈に特化) として併存。本モジュールは
 * 「resource を指す URL」の単一真理。
 */

export type ResourceKind =
  | 'task'
  | 'document'
  | 'document_full'
  | 'bookmark'
  | 'knowledge'
  | 'docsite_page'
  | 'project'
  | 'unknown'

export const ALLOWED_KINDS_FOR_BUILD = [
  'task',
  'document',
  'document_full',
  'bookmark',
  'knowledge',
  'docsite_page',
  'project',
] as const satisfies readonly ResourceKind[]

/** 個人 layout 帰属で URL から削除されるキー (仕様書 §3 / §6)。 */
export const LAYOUT_QUERY_KEYS: readonly string[] = ['view', 'layout', 'group']

const RECOGNISED_QUERY_KEYS = new Set(['task', 'doc'])

const OBJECT_ID_RE = /^[a-f0-9]{24}$/

const ALLOWED_HOSTS = new Set(['todo.vtech-studios.com'])

const PROD_ORIGIN = 'https://todo.vtech-studios.com'

const PATH_TRAVERSAL_RE = /(^|\/)(\.|\.\.)(\/|$)/

export interface ParsedUrl {
  kind: ResourceKind
  projectId?: string
  resourceId?: string
  path?: string
  siteId?: string
  hadUnknownParams: boolean
  /** legacy redirect target if applicable (`/workbench/{id}` → `/projects/{id}`) */
  redirectTo?: string
}

export interface BuildUrlOpts {
  projectId?: string
  resourceId?: string
  path?: string
  siteId?: string
  /** 絶対 URL (origin 付き) を返すか。クリップボードコピー用は ``true``。 */
  absolute?: boolean
}

function isObjectId(value: string): boolean {
  return OBJECT_ID_RE.test(value)
}

function originAllowed(hostname: string): boolean {
  const lc = hostname.toLowerCase()
  if (ALLOWED_HOSTS.has(lc)) return true
  if (lc === 'localhost') return true
  return false
}

function normalisePath(rawPath: string): string[] | null {
  if (rawPath === '' || rawPath === '/') return []
  let stripped = rawPath.replace(/^\/+/, '')
  if (stripped.endsWith('/')) stripped = stripped.replace(/\/+$/, '')
  if (stripped === '') return []
  const segments = stripped.split('/')
  for (const s of segments) {
    if (s === '' || s === '.' || s === '..') return null
  }
  return segments
}

function splitQuery(
  query: string,
): { dict: Record<string, string>; hadUnknown: boolean } {
  const out: Record<string, string> = {}
  let hadUnknown = false
  const params = new URLSearchParams(query)
  for (const [k, v] of params) {
    if (RECOGNISED_QUERY_KEYS.has(k)) {
      out[k] = v
    } else {
      hadUnknown = true
    }
  }
  return { dict: out, hadUnknown }
}

/** スキーム付きかどうか (``http://`` / ``https://`` 等)。 */
const SCHEME_RE = /^[a-z][a-z0-9+.-]*:/i

/**
 * URL を解析して routing メタデータを返す。仕様書 §4.3 §3 の解析
 * 優先順位に厳密に従う。認可チェックは backend MCP layer の責務。
 *
 * 注意: ``URL`` コンストラクタは pathname の ``..`` ``.`` を黙って
 * 正規化してしまう (例: ``/a/../b`` → ``/b``)。これだと path
 * traversal の検知が外れるため、本関数は **raw 文字列** から path /
 * query を切り出す。host 名のみ ``URL`` で parse して origin allowlist
 * チェックに使う。
 */
export function parseUrl(url: string): ParsedUrl {
  if (typeof url !== 'string' || url.trim() === '') {
    return { kind: 'unknown', hadUnknownParams: false }
  }

  // Strip URL fragment (#section). 本仕様では fragment は無視する。
  const noHash = url.split('#')[0]

  let pathPart: string
  let queryPart: string

  if (SCHEME_RE.test(noHash)) {
    // absolute URL — host を URL で parse して allowlist チェック.
    let parsed: URL
    try {
      parsed = new URL(noHash)
    } catch {
      return { kind: 'unknown', hadUnknownParams: false }
    }
    if (!originAllowed(parsed.hostname)) {
      return { kind: 'unknown', hadUnknownParams: false }
    }
    // raw path/query を input から切り出す (URL pathname の正規化を避ける).
    const schemeEnd = noHash.indexOf('://')
    const afterScheme = noHash.slice(schemeEnd + 3)
    const slashIdx = afterScheme.indexOf('/')
    const afterHost = slashIdx < 0 ? '' : afterScheme.slice(slashIdx)
    const qIdx = afterHost.indexOf('?')
    if (qIdx < 0) {
      pathPart = afterHost
      queryPart = ''
    } else {
      pathPart = afterHost.slice(0, qIdx)
      queryPart = afterHost.slice(qIdx + 1)
    }
  } else {
    // relative — そのまま path/query 切り出し.
    const qIdx = noHash.indexOf('?')
    if (qIdx < 0) {
      pathPart = noHash
      queryPart = ''
    } else {
      pathPart = noHash.slice(0, qIdx)
      queryPart = noHash.slice(qIdx + 1)
    }
  }

  const { dict: queryDict, hadUnknown: hadUnknownParams } = splitQuery(queryPart)

  const segments = normalisePath(pathPart)
  if (segments === null) {
    return { kind: 'unknown', hadUnknownParams }
  }

  // legacy: /workbench/{pid} → kind=project + redirectTo=/projects/{pid}
  if (segments.length === 2 && segments[0] === 'workbench') {
    const pid = segments[1]
    if (isObjectId(pid)) {
      return {
        kind: 'project',
        projectId: pid,
        redirectTo: `/projects/${pid}`,
        hadUnknownParams,
      }
    }
    return { kind: 'unknown', hadUnknownParams }
  }

  // /projects/{pid}/documents/{did} → document_full
  if (
    segments.length === 4 &&
    segments[0] === 'projects' &&
    segments[2] === 'documents'
  ) {
    const pid = segments[1]
    const did = segments[3]
    if (!isObjectId(pid) || !isObjectId(did)) {
      return { kind: 'unknown', hadUnknownParams }
    }
    return {
      kind: 'document_full',
      projectId: pid,
      resourceId: did,
      hadUnknownParams,
    }
  }

  // /projects/{pid} (+ optional ?task / ?doc)
  if (segments.length === 2 && segments[0] === 'projects') {
    const pid = segments[1]
    if (!isObjectId(pid)) return { kind: 'unknown', hadUnknownParams }
    if ('task' in queryDict) {
      const tid = queryDict.task
      if (isObjectId(tid)) {
        return {
          kind: 'task',
          projectId: pid,
          resourceId: tid,
          hadUnknownParams,
        }
      }
      // task ID が形式違反 → kind=project に degrade、hadUnknownParams=true
      return { kind: 'project', projectId: pid, hadUnknownParams: true }
    }
    if ('doc' in queryDict) {
      const did = queryDict.doc
      if (isObjectId(did)) {
        return {
          kind: 'document',
          projectId: pid,
          resourceId: did,
          hadUnknownParams,
        }
      }
      return { kind: 'project', projectId: pid, hadUnknownParams: true }
    }
    return { kind: 'project', projectId: pid, hadUnknownParams }
  }

  // /bookmarks/{bid}
  if (segments.length === 2 && segments[0] === 'bookmarks') {
    const bid = segments[1]
    if (!isObjectId(bid)) return { kind: 'unknown', hadUnknownParams }
    return { kind: 'bookmark', resourceId: bid, hadUnknownParams }
  }

  // /knowledge/{kid}
  if (segments.length === 2 && segments[0] === 'knowledge') {
    const kid = segments[1]
    if (!isObjectId(kid)) return { kind: 'unknown', hadUnknownParams }
    return { kind: 'knowledge', resourceId: kid, hadUnknownParams }
  }

  // /docsites/{sid}/{rest...} → docsite_page
  if (segments.length >= 3 && segments[0] === 'docsites') {
    const sid = segments[1]
    if (!isObjectId(sid)) return { kind: 'unknown', hadUnknownParams }
    const subPath = segments.slice(2).join('/')
    return {
      kind: 'docsite_page',
      siteId: sid,
      path: subPath,
      hadUnknownParams,
    }
  }

  return { kind: 'unknown', hadUnknownParams }
}

function requireField(
  value: string | undefined,
  name: 'projectId' | 'resourceId' | 'siteId' | 'path',
  kind: ResourceKind,
): string {
  if (!value) {
    throw new Error(`buildUrl: missing required ${name} for kind=${kind}`)
  }
  if (
    (name === 'projectId' || name === 'resourceId' || name === 'siteId') &&
    !isObjectId(value)
  ) {
    throw new Error(`buildUrl: invalid id format for ${name}: ${value}`)
  }
  return value
}

/**
 * 仕様書 §4.2 — URL を生成する。round-trip: ``parseUrl(buildUrl(kind,
 * opts))`` が同じ ids を返す (URL-1)。
 */
export function buildUrl(kind: ResourceKind, opts: BuildUrlOpts = {}): string {
  if (!(ALLOWED_KINDS_FOR_BUILD as readonly string[]).includes(kind)) {
    throw new Error(`buildUrl: unsupported kind: ${kind}`)
  }

  let path: string
  switch (kind) {
    case 'task': {
      const pid = requireField(opts.projectId, 'projectId', kind)
      const rid = requireField(opts.resourceId, 'resourceId', kind)
      path = `/projects/${pid}?task=${rid}`
      break
    }
    case 'document': {
      const pid = requireField(opts.projectId, 'projectId', kind)
      const rid = requireField(opts.resourceId, 'resourceId', kind)
      path = `/projects/${pid}?doc=${rid}`
      break
    }
    case 'document_full': {
      const pid = requireField(opts.projectId, 'projectId', kind)
      const rid = requireField(opts.resourceId, 'resourceId', kind)
      path = `/projects/${pid}/documents/${rid}`
      break
    }
    case 'bookmark': {
      const rid = requireField(opts.resourceId, 'resourceId', kind)
      path = `/bookmarks/${rid}`
      break
    }
    case 'knowledge': {
      const rid = requireField(opts.resourceId, 'resourceId', kind)
      path = `/knowledge/${rid}`
      break
    }
    case 'docsite_page': {
      const sid = requireField(opts.siteId, 'siteId', kind)
      const p = opts.path
      if (!p) {
        throw new Error(
          "buildUrl: missing required path for kind='docsite_page'",
        )
      }
      if (PATH_TRAVERSAL_RE.test(p) || p.startsWith('/')) {
        throw new Error(
          `buildUrl: invalid docsite path (traversal/leading slash): ${p}`,
        )
      }
      path = `/docsites/${sid}/${p}`
      break
    }
    case 'project': {
      const pid = requireField(opts.projectId, 'projectId', kind)
      path = `/projects/${pid}`
      break
    }
    case 'unknown':
    default:
      throw new Error(`buildUrl: cannot build "unknown" kind`)
  }

  if (opts.absolute) {
    return `${PROD_ORIGIN}${path}`
  }
  return path
}
