import { describe, expect, it } from 'vitest'

import type { FileContent } from '../../lib/api'
import { initialTabs, isDirty, tabsReducer, type TabsState } from './tabs'

function file(path: string, content: string | null = 'text', hash = `h-${path}`): FileContent {
  return { path, content, hash, size: content?.length ?? 0, binary: content === null, too_large: false }
}

function open(...paths: string[]): TabsState {
  return paths.reduce((s, p) => tabsReducer(s, { type: 'opened', file: file(p) }), initialTabs)
}

describe('tabsReducer', () => {
  it('opens files once and activates them', () => {
    let state = open('a.ts', 'b.ts')
    expect(state.tabs.map((t) => t.path)).toEqual(['a.ts', 'b.ts'])
    expect(state.active).toBe('b.ts')

    state = tabsReducer(state, { type: 'opened', file: file('a.ts', 'newer') })
    expect(state.tabs).toHaveLength(2)
    expect(state.tabs[0].content).toBe('text') // re-opening keeps unsaved edits
    expect(state.active).toBe('a.ts')
  })

  it('closing the active tab activates its neighbour', () => {
    let state = tabsReducer(open('a.ts', 'b.ts', 'c.ts'), { type: 'activate', path: 'b.ts' })
    state = tabsReducer(state, { type: 'close', path: 'b.ts' })
    expect(state.active).toBe('c.ts')
    state = tabsReducer(state, { type: 'close', path: 'c.ts' })
    expect(state.active).toBe('a.ts')
    state = tabsReducer(state, { type: 'close', path: 'a.ts' })
    expect(state).toEqual(initialTabs)
  })

  it('tracks dirty state across edit and save', () => {
    let state = tabsReducer(open('a.ts'), { type: 'edit', path: 'a.ts', content: 'changed' })
    expect(isDirty(state.tabs[0])).toBe(true)

    state = tabsReducer(state, { type: 'saveStarted', path: 'a.ts' })
    expect(state.tabs[0].saving).toBe(true)
    state = tabsReducer(state, { type: 'saved', path: 'a.ts', hash: 'h2', content: 'changed' })
    expect(state.tabs[0]).toMatchObject({ saving: false, hash: 'h2', savedContent: 'changed' })
    expect(isDirty(state.tabs[0])).toBe(false)
  })

  it('edits made while a save is in flight stay dirty', () => {
    let state = tabsReducer(open('a.ts'), { type: 'edit', path: 'a.ts', content: 'v1' })
    state = tabsReducer(state, { type: 'saveStarted', path: 'a.ts' })
    state = tabsReducer(state, { type: 'edit', path: 'a.ts', content: 'v2' })
    state = tabsReducer(state, { type: 'saved', path: 'a.ts', hash: 'h1', content: 'v1' })
    expect(isDirty(state.tabs[0])).toBe(true)
  })

  it('records conflicts without losing edits, and reload replaces them', () => {
    let state = tabsReducer(open('a.ts'), { type: 'edit', path: 'a.ts', content: 'mine' })
    state = tabsReducer(state, { type: 'conflict', path: 'a.ts', currentHash: 'disk' })
    expect(state.tabs[0]).toMatchObject({ content: 'mine', conflict: { currentHash: 'disk' } })

    state = tabsReducer(state, { type: 'reloaded', file: file('a.ts', 'theirs', 'disk') })
    expect(state.tabs[0]).toMatchObject({ content: 'theirs', hash: 'disk', conflict: null })
    expect(isDirty(state.tabs[0])).toBe(false)
  })

  it('marks binary files as non-editable', () => {
    const state = open('img.png')
    const binary = tabsReducer(state, { type: 'opened', file: file('logo.png', null) })
    expect(binary.tabs[1]).toMatchObject({ content: null, binary: true })
  })
})
