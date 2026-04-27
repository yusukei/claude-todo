/**
 * URL Contract — frontend ``lib/urlContract.ts`` (URL S5).
 *
 * 仕様書: ``docs/api/url-contract.md``
 * 共有 fixture: ``docs/api/url-contract.fixtures.json``
 *
 * Backend ``backend/tests/unit/test_url_contract.py`` と **同じ fixture**
 * を読むことで spec drift を防ぐ。Round-trip 不変条件 (URL-1) は backend
 * と frontend 両方で同じ ids を返すことで担保。
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  ALLOWED_KINDS_FOR_BUILD,
  LAYOUT_QUERY_KEYS,
  type ResourceKind,
  buildUrl,
  parseUrl,
} from '../../lib/urlContract'

interface FixtureValid {
  name: string
  kind: ResourceKind
  buildOpts: {
    projectId?: string
    resourceId?: string
    path?: string
    siteId?: string
  }
  url: string
  parsed: {
    kind: ResourceKind
    projectId?: string
    resourceId?: string
    path?: string
    siteId?: string
    hadUnknownParams: boolean
  }
}

interface FixtureWithUnknownParams {
  name: string
  url: string
  parsed: {
    kind: ResourceKind
    projectId?: string
    resourceId?: string
    hadUnknownParams: boolean
  }
}

interface FixtureLegacy {
  name: string
  url: string
  parsed: {
    kind: ResourceKind
    projectId?: string
    redirectTo?: string
    hadUnknownParams: boolean
  }
}

interface FixtureAbsolute {
  name: string
  url: string
  parsed: {
    kind: ResourceKind
    projectId?: string
    resourceId?: string
    hadUnknownParams: boolean
  }
}

interface FixtureInvalid {
  name: string
  url: string
  parsed: {
    kind: ResourceKind
    projectId?: string
    hadUnknownParams: boolean
  }
}

interface Fixtures {
  valid: FixtureValid[]
  with_unknown_params: FixtureWithUnknownParams[]
  legacy: FixtureLegacy[]
  absolute_url: FixtureAbsolute[]
  invalid: FixtureInvalid[]
  trailing_slash: FixtureValid[]
}

function findFixturePath(): string {
  const here = fileURLToPath(import.meta.url)
  let dir = path.dirname(here)
  while (dir !== path.dirname(dir)) {
    const candidate = path.join(
      dir,
      'docs',
      'api',
      'url-contract.fixtures.json',
    )
    if (fs.existsSync(candidate)) return candidate
    dir = path.dirname(dir)
  }
  throw new Error(
    `URL contract fixture not found in any ancestor of ${here}. ` +
      "Expected 'docs/api/url-contract.fixtures.json' under repo root.",
  )
}

const fixtures: Fixtures = JSON.parse(
  fs.readFileSync(findFixturePath(), 'utf-8'),
)

// ── URL-4: 未知 URL → kind: 'unknown' ──────────────────────────────


describe('parseUrl — invalid / unknown', () => {
  it('empty string → unknown', () => {
    expect(parseUrl('').kind).toBe('unknown')
  })

  it('whitespace-only → unknown', () => {
    expect(parseUrl('   ').kind).toBe('unknown')
  })

  it('non-string defensive guard → unknown', () => {
    // @ts-expect-error runtime defensive check
    expect(parseUrl(null).kind).toBe('unknown')
    // @ts-expect-error runtime defensive check
    expect(parseUrl(undefined).kind).toBe('unknown')
  })

  it.each(fixtures.invalid)('fixture: $name → kind=$parsed.kind', (c) => {
    const result = parseUrl(c.url)
    expect(result.kind).toBe(c.parsed.kind)
    if (c.parsed.hadUnknownParams !== undefined) {
      expect(result.hadUnknownParams).toBe(c.parsed.hadUnknownParams)
    }
  })
})


// ── URL-1: round-trip 不変 (build_url → parse_url) ────────────────


describe('round-trip: buildUrl → parseUrl', () => {
  it.each(fixtures.valid)(
    'fixture: $name → builds and parses back the same ids',
    (c) => {
      const built = buildUrl(c.kind, c.buildOpts)
      expect(built).toBe(c.url)

      const parsed = parseUrl(built)
      expect(parsed.kind).toBe(c.kind)
      if (c.buildOpts.projectId !== undefined) {
        expect(parsed.projectId).toBe(c.buildOpts.projectId)
      }
      if (c.buildOpts.resourceId !== undefined) {
        expect(parsed.resourceId).toBe(c.buildOpts.resourceId)
      }
      if (c.buildOpts.siteId !== undefined) {
        expect(parsed.siteId).toBe(c.buildOpts.siteId)
      }
      if (c.buildOpts.path !== undefined) {
        expect(parsed.path).toBe(c.buildOpts.path)
      }
      expect(parsed.hadUnknownParams).toBe(false)
    },
  )
})


// ── URL-2: 個人 layout query は parse 時に hadUnknownParams ───────


describe('parseUrl — individual layout queries trigger hadUnknownParams', () => {
  it.each(fixtures.with_unknown_params)(
    'fixture: $name → kind=$parsed.kind + hadUnknownParams=true',
    (c) => {
      const parsed = parseUrl(c.url)
      expect(parsed.kind).toBe(c.parsed.kind)
      expect(parsed.hadUnknownParams).toBe(true)
    },
  )

  it('buildUrl never emits layout query keys', () => {
    const samples: { kind: ResourceKind; opts: Record<string, string> }[] = [
      { kind: 'task', opts: { projectId: 'a'.repeat(24), resourceId: 'b'.repeat(24) } },
      { kind: 'document', opts: { projectId: 'a'.repeat(24), resourceId: 'b'.repeat(24) } },
      { kind: 'project', opts: { projectId: 'a'.repeat(24) } },
      { kind: 'bookmark', opts: { resourceId: 'c'.repeat(24) } },
      { kind: 'knowledge', opts: { resourceId: 'd'.repeat(24) } },
      {
        kind: 'docsite_page',
        opts: { siteId: 'e'.repeat(24), path: 'intro/getting-started' },
      },
    ]
    for (const { kind, opts } of samples) {
      const url = buildUrl(kind, opts)
      for (const key of LAYOUT_QUERY_KEYS) {
        expect(url).not.toContain(`${key}=`)
      }
    }
  })
})


// ── URL-3: legacy /workbench/{id} → redirect_to /projects/{id} ────


describe('parseUrl — legacy redirect', () => {
  it.each(fixtures.legacy)(
    'fixture: $name → redirectTo=$parsed.redirectTo',
    (c) => {
      const parsed = parseUrl(c.url)
      expect(parsed.kind).toBe(c.parsed.kind)
      expect(parsed.projectId).toBe(c.parsed.projectId)
      expect(parsed.redirectTo).toBe(c.parsed.redirectTo)
    },
  )

  it('legacy /workbench/{id} with invalid id → unknown', () => {
    expect(parseUrl('/workbench/short-id').kind).toBe('unknown')
  })
})


// ── absolute URL の origin allowlist ──────────────────────────────


describe('parseUrl — absolute URL origin allowlist', () => {
  it.each(fixtures.absolute_url)(
    'fixture: $name → kind=$parsed.kind',
    (c) => {
      const parsed = parseUrl(c.url)
      expect(parsed.kind).toBe(c.parsed.kind)
      if (c.parsed.projectId !== undefined) {
        expect(parsed.projectId).toBe(c.parsed.projectId)
      }
      if (c.parsed.resourceId !== undefined) {
        expect(parsed.resourceId).toBe(c.parsed.resourceId)
      }
    },
  )

  it('unknown origin → unknown', () => {
    expect(
      parseUrl('https://evil.example.com/projects/' + 'a'.repeat(24)).kind,
    ).toBe('unknown')
  })
})


// ── trailing slash 正規化 ────────────────────────────────────────


describe('parseUrl — trailing slash normalisation', () => {
  it.each(fixtures.trailing_slash)(
    'fixture: $name → kind=$parsed.kind',
    (c) => {
      const parsed = parseUrl(c.url)
      expect(parsed.kind).toBe(c.parsed.kind)
      if (c.parsed.projectId !== undefined) {
        expect(parsed.projectId).toBe(c.parsed.projectId)
      }
      if (c.parsed.resourceId !== undefined) {
        expect(parsed.resourceId).toBe(c.parsed.resourceId)
      }
    },
  )
})


// ── docsite_page path traversal 防御 ──────────────────────────────


describe('parseUrl — docsite_page path safety', () => {
  it('rejects path with .. segment', () => {
    const sid = '1'.repeat(24)
    expect(parseUrl(`/docsites/${sid}/intro/../secret`).kind).toBe('unknown')
  })

  it('rejects path with . segment', () => {
    const sid = '1'.repeat(24)
    expect(parseUrl(`/docsites/${sid}/./intro`).kind).toBe('unknown')
  })

  it('accepts multi-segment path', () => {
    const sid = '1'.repeat(24)
    const parsed = parseUrl(`/docsites/${sid}/a/b/c`)
    expect(parsed.kind).toBe('docsite_page')
    expect(parsed.siteId).toBe(sid)
    expect(parsed.path).toBe('a/b/c')
  })
})


// ── buildUrl の入力 validation ──────────────────────────────────


describe('buildUrl — input validation', () => {
  it('rejects missing required ids', () => {
    expect(() => buildUrl('task', { projectId: 'a'.repeat(24) })).toThrow(
      /missing required/,
    )
  })

  it('rejects invalid ObjectId', () => {
    expect(() =>
      buildUrl('task', {
        projectId: 'too-short',
        resourceId: 'b'.repeat(24),
      }),
    ).toThrow(/invalid id format/)
  })

  it('rejects unsupported kind ("unknown")', () => {
    expect(() =>
      buildUrl('unknown', { projectId: 'a'.repeat(24) }),
    ).toThrow(/unsupported kind/)
  })

  it('rejects docsite path with traversal', () => {
    expect(() =>
      buildUrl('docsite_page', {
        siteId: '1'.repeat(24),
        path: 'intro/../etc',
      }),
    ).toThrow(/invalid docsite path/)
  })

  it('rejects docsite path with leading slash', () => {
    expect(() =>
      buildUrl('docsite_page', {
        siteId: '1'.repeat(24),
        path: '/intro',
      }),
    ).toThrow(/invalid docsite path/)
  })

  it('absolute=true yields production origin URL', () => {
    const pid = 'a'.repeat(24)
    const tid = 'b'.repeat(24)
    const url = buildUrl('task', {
      projectId: pid,
      resourceId: tid,
      absolute: true,
    })
    expect(url).toBe(
      `https://todo.vtech-studios.com/projects/${pid}?task=${tid}`,
    )
  })

  it('absolute=true round-trips through parseUrl', () => {
    const pid = 'a'.repeat(24)
    const did = 'b'.repeat(24)
    const url = buildUrl('document_full', {
      projectId: pid,
      resourceId: did,
      absolute: true,
    })
    const parsed = parseUrl(url)
    expect(parsed.kind).toBe('document_full')
    expect(parsed.projectId).toBe(pid)
    expect(parsed.resourceId).toBe(did)
  })
})


// ── ALLOWED_KINDS_FOR_BUILD const ─────────────────────────────────


describe('module exports', () => {
  it('ALLOWED_KINDS_FOR_BUILD has 7 kinds (no "unknown")', () => {
    expect(ALLOWED_KINDS_FOR_BUILD).toHaveLength(7)
    expect(ALLOWED_KINDS_FOR_BUILD).not.toContain('unknown')
  })

  it('LAYOUT_QUERY_KEYS contains view/layout/group', () => {
    expect(LAYOUT_QUERY_KEYS).toEqual(
      expect.arrayContaining(['view', 'layout', 'group']),
    )
  })
})
