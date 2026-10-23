import type { FileContent } from '../../lib/api'

export interface EditorTab {
  path: string
  /** Current editor text (null for binary / too-large files, which are not editable). */
  content: string | null
  /** Text as last read from or written to disk. */
  savedContent: string | null
  /** Hash of the on-disk version this tab is based on; sent as base_hash when saving. */
  hash: string
  binary: boolean
  tooLarge: boolean
  saving: boolean
  /** Set when a save was rejected because the file changed on disk. */
  conflict: { currentHash: string | null } | null
  error: string | null
}

export interface TabsState {
  tabs: EditorTab[]
  active: string | null
}

export type TabsAction =
  | { type: 'opened'; file: FileContent }
  | { type: 'activate'; path: string }
  | { type: 'close'; path: string }
  | { type: 'closeAll' }
  | { type: 'edit'; path: string; content: string }
  | { type: 'saveStarted'; path: string }
  | { type: 'saved'; path: string; hash: string; content: string }
  | { type: 'saveFailed'; path: string; error: string }
  | { type: 'conflict'; path: string; currentHash: string | null }
  | { type: 'reloaded'; file: FileContent }

export const initialTabs: TabsState = { tabs: [], active: null }

export function isDirty(tab: EditorTab): boolean {
  return tab.content !== tab.savedContent
}

function fromFile(file: FileContent): EditorTab {
  return {
    path: file.path,
    content: file.content,
    savedContent: file.content,
    hash: file.hash,
    binary: file.binary,
    tooLarge: file.too_large,
    saving: false,
    conflict: null,
    error: null
  }
}

function update(state: TabsState, path: string, patch: (tab: EditorTab) => Partial<EditorTab>): TabsState {
  return {
    ...state,
    tabs: state.tabs.map((tab) => (tab.path === path ? { ...tab, ...patch(tab) } : tab))
  }
}

export function tabsReducer(state: TabsState, action: TabsAction): TabsState {
  switch (action.type) {
    case 'opened': {
      const exists = state.tabs.some((t) => t.path === action.file.path)
      return {
        tabs: exists ? state.tabs : [...state.tabs, fromFile(action.file)],
        active: action.file.path
      }
    }
    case 'activate':
      return { ...state, active: action.path }
    case 'close': {
      const index = state.tabs.findIndex((t) => t.path === action.path)
      if (index === -1) return state
      const tabs = state.tabs.filter((t) => t.path !== action.path)
      const active =
        state.active === action.path ? (tabs[Math.min(index, tabs.length - 1)]?.path ?? null) : state.active
      return { tabs, active }
    }
    case 'closeAll':
      return initialTabs
    case 'edit':
      return update(state, action.path, () => ({ content: action.content }))
    case 'saveStarted':
      return update(state, action.path, () => ({ saving: true, error: null }))
    case 'saved':
      return update(state, action.path, () => ({
        saving: false,
        hash: action.hash,
        savedContent: action.content,
        conflict: null
      }))
    case 'saveFailed':
      return update(state, action.path, () => ({ saving: false, error: action.error }))
    case 'conflict':
      return update(state, action.path, () => ({
        saving: false,
        conflict: { currentHash: action.currentHash }
      }))
    case 'reloaded':
      return update(state, action.file.path, () => fromFile(action.file))
  }
}
