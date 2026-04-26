/**
 * URL contract test fixture — superseded.
 *
 * The original D0 stubs (`describe.skip` placeholders for D3
 * implementation) have been absorbed into concrete tests:
 *
 *   - INV-1 / INV-2 bijection + focused pane sync
 *       → ``components/WorkbenchPage.sync.test.tsx`` (P9, P10, P16, P17)
 *       → ``components/TaskDetailPane.test.tsx`` (TD2)
 *       → ``unit/urlContract.test.ts`` (parse / serialise / round-trip)
 *
 *   - INV-7 unknown value fallback
 *       → ``unit/urlContract.test.ts``
 *         (`falls back + flags unknown when ?view= is gibberish`)
 *
 *   - INV-8 localStorage quota
 *       → ``unit/storage.test.ts`` (ST7)
 *
 *   - INV-12 multi TaskDetailPane focus arbitration
 *       → ``components/TaskDetailPane.test.tsx`` (TD2)
 *
 *   - INV-15 keep-mount + WS
 *       → ``components/TabGroup.keepAlive.test.tsx`` (L3 / L4)
 *
 *   - INV-17 SSE 1 connection
 *       → ``hooks/useSSE.workbench.test.ts`` (P15)
 *
 * The file is kept (empty of test bodies) so the cross-reference
 * survives. ``describe.skip`` placeholders were removed because they
 * showed up as deferred work that is no longer deferred.
 */
export {}
