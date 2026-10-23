import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ApiError, type ApiClient, type TreeEntry } from '../../lib/api'
import { FileTree } from './FileTree'

const TREE: Record<string, TreeEntry[]> = {
  '': [
    { name: 'src', path: 'src', type: 'directory', size: null },
    { name: 'README.md', path: 'README.md', type: 'file', size: 7 }
  ],
  src: [{ name: 'app.ts', path: 'src/app.ts', type: 'file', size: 19 }]
}

function fakeApi(tree = TREE): ApiClient & { get: ReturnType<typeof vi.fn> } {
  return {
    get: vi.fn(async (_path: string, query?: Record<string, string | undefined>) => {
      const entries = tree[query?.path ?? '']
      if (!entries) throw new ApiError(404, 'directory not found', null)
      return entries
    }),
    post: vi.fn(),
    put: vi.fn()
  } as never
}

describe('FileTree', () => {
  it('loads the root, then lazily loads a directory when expanded', async () => {
    const api = fakeApi()
    render(<FileTree api={api} projectId="p1" activePath={null} onOpenFile={() => {}} />)

    const src = await screen.findByRole('treeitem', { name: 'src' })
    expect(screen.getByRole('treeitem', { name: 'README.md' })).toBeInTheDocument()
    expect(api.get).toHaveBeenCalledTimes(1)
    expect(api.get).toHaveBeenCalledWith('/projects/p1/tree', { path: '' })
    expect(src).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(src)
    expect(await screen.findByRole('treeitem', { name: 'app.ts' })).toBeInTheDocument()
    expect(src).toHaveAttribute('aria-expanded', 'true')
    expect(api.get).toHaveBeenLastCalledWith('/projects/p1/tree', { path: 'src' })

    // Collapsing and re-expanding uses the cached listing.
    fireEvent.click(src)
    fireEvent.click(src)
    expect(api.get).toHaveBeenCalledTimes(2)
  })

  it('opens files and marks the active one', async () => {
    const onOpenFile = vi.fn()
    render(<FileTree api={fakeApi()} projectId="p1" activePath="README.md" onOpenFile={onOpenFile} />)

    const readme = await screen.findByRole('treeitem', { name: 'README.md' })
    expect(readme).toHaveAttribute('aria-selected', 'true')
    fireEvent.click(readme)
    expect(onOpenFile).toHaveBeenCalledWith('README.md')
  })

  it('shows load errors inline', async () => {
    render(<FileTree api={fakeApi({})} projectId="p1" activePath={null} onOpenFile={() => {}} />)
    expect(await screen.findByText('directory not found')).toBeInTheDocument()
  })
})
