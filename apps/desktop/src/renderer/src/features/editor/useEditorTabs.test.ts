import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ApiError, type ApiClient, type FileContent } from '../../lib/api'
import { useEditorTabs } from './useEditorTabs'

const FILE: FileContent = {
  path: 'src/app.ts',
  content: 'one',
  hash: 'h1',
  size: 3,
  binary: false,
  too_large: false
}

function fakeApi(put: ApiClient['put']): ApiClient {
  return { get: vi.fn().mockResolvedValue(FILE), post: vi.fn(), put } as unknown as ApiClient
}

async function setup(put: ApiClient['put']) {
  const api = fakeApi(put)
  const onClosed = vi.fn()
  const hook = renderHook(() => useEditorTabs(api, 'p1', onClosed))
  await act(() => hook.result.current.openFile('src/app.ts'))
  return { hook, api, onClosed }
}

describe('useEditorTabs', () => {
  it('saves the latest content when save follows an edit in the same tick', async () => {
    const put = vi.fn().mockResolvedValue({ path: 'src/app.ts', hash: 'h2' })
    const { hook } = await setup(put)

    await act(async () => {
      hook.result.current.edit('src/app.ts', 'two')
      await hook.result.current.save('src/app.ts') // no render in between (e.g. fast Ctrl+S)
    })

    expect(put).toHaveBeenCalledWith('/projects/p1/file', {
      path: 'src/app.ts',
      content: 'two',
      base_hash: 'h1'
    })
    expect(hook.result.current.state.tabs[0]).toMatchObject({ hash: 'h2', savedContent: 'two' })
  })

  it('records a conflict, then overwrite sends the on-disk hash', async () => {
    const put = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(409, 'file changed on disk', { current_hash: 'disk' }))
      .mockResolvedValueOnce({ path: 'src/app.ts', hash: 'h3' })
    const { hook } = await setup(put)

    await act(async () => {
      hook.result.current.edit('src/app.ts', 'mine')
      await hook.result.current.save('src/app.ts')
    })
    expect(hook.result.current.state.tabs[0].conflict).toEqual({ currentHash: 'disk' })

    await act(() => hook.result.current.overwrite('src/app.ts'))
    expect(put).toHaveBeenLastCalledWith('/projects/p1/file', {
      path: 'src/app.ts',
      content: 'mine',
      base_hash: 'disk'
    })
    expect(hook.result.current.state.tabs[0]).toMatchObject({ conflict: null, hash: 'h3' })
  })

  it('does not save unchanged files and reports other errors', async () => {
    const put = vi.fn().mockRejectedValue(new ApiError(500, 'HTTP 500', null))
    const { hook } = await setup(put)

    await act(() => hook.result.current.save('src/app.ts'))
    expect(put).not.toHaveBeenCalled()

    await act(async () => {
      hook.result.current.edit('src/app.ts', 'x')
      await hook.result.current.save('src/app.ts')
    })
    expect(hook.result.current.state.tabs[0]).toMatchObject({ error: 'HTTP 500', saving: false })
  })

  it('reports closed tabs so editor models can be disposed', async () => {
    const { hook, onClosed } = await setup(vi.fn())
    act(() => hook.result.current.close('src/app.ts'))
    expect(onClosed).toHaveBeenCalledWith('p1', 'src/app.ts')
    expect(hook.result.current.state.tabs).toEqual([])
  })
})
