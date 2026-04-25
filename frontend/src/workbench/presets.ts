/**
 * Built-in starting layouts. Each preset returns a freshly
 * constructed ``LayoutTree`` (calling the helpers in ``treeUtils``)
 * so caller code can drop the result straight into the reducer
 * without worrying about shared id collisions across presets.
 */
import type { LayoutTree } from './types'
import { makePane, makeSplitNode, makeTabsNode } from './treeUtils'

export interface PresetDefinition {
  id: string
  /** Short label shown in the menu. */
  label: string
  /** One-line description shown as a menu tooltip. */
  description: string
  /** Lazy because each invocation must allocate fresh node ids. */
  build: () => LayoutTree
}

/** "Tasks only" — the default empty layout, also used by the
 *  Cmd+Shift+R reset shortcut. */
const tasksOnly: PresetDefinition = {
  id: 'tasks-only',
  label: 'Tasks only',
  description: 'Single tab group with a Tasks pane (default / reset).',
  build: () => makeTabsNode([makePane('tasks', {})]),
}

/** Tasks on top, Terminal below — the basic "watch tasks while
 *  running commands" config. */
const tasksOverTerminal: PresetDefinition = {
  id: 'tasks-over-terminal',
  label: 'Tasks + Terminal',
  description: 'Tasks above, Terminal below (vertical split).',
  build: () =>
    makeSplitNode('vertical', [
      makeTabsNode([makePane('tasks', {})]),
      makeTabsNode([makePane('terminal', {})]),
    ]),
}

/** Tasks on the left, Doc + Terminal stacked on the right. */
const threeWay: PresetDefinition = {
  id: 'three-way',
  label: 'Tasks + Doc + Terminal',
  description: 'Tasks on the left; Doc above Terminal on the right.',
  build: () =>
    makeSplitNode('horizontal', [
      makeTabsNode([makePane('tasks', {})]),
      makeSplitNode('vertical', [
        makeTabsNode([makePane('doc', {})]),
        makeTabsNode([makePane('terminal', {})]),
      ]),
    ]),
}

/** Doc on the left, file browser on the right — for editing
 *  documentation while consulting the workspace tree. */
const docPlusFileBrowser: PresetDefinition = {
  id: 'doc-plus-files',
  label: 'Doc + Files',
  description: 'Doc on the left, File browser on the right.',
  build: () =>
    makeSplitNode('horizontal', [
      makeTabsNode([makePane('doc', {})]),
      makeTabsNode([makePane('file-browser', {})]),
    ]),
}

export const PRESETS: PresetDefinition[] = [
  tasksOnly,
  tasksOverTerminal,
  threeWay,
  docPlusFileBrowser,
]

/** Look up a preset by id. Useful for tests and the reset
 *  shortcut. */
export function getPreset(id: string): PresetDefinition | undefined {
  return PRESETS.find((p) => p.id === id)
}
