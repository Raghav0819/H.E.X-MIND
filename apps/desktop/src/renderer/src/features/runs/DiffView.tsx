import { DiffEditor } from '@monaco-editor/react'
import { X } from 'lucide-react'
import { useEffect, useState } from 'react'

import { EmptyState } from '../../components/Panel'
import type { ApiClient, RunDiff } from '../../lib/api'
import { HEX_THEME } from '../editor/monaco'

const CHANGE_LABEL = { added: 'A', modified: 'M', deleted: 'D' } as const

interface Props {
  api: ApiClient
  runId: string
  onClose: () => void
}

/** Read-only review of a run's proposed changes (applying them arrives in M6). */
export function DiffView({ api, runId, onClose }: Props) {
  const [diff, setDiff] = useState<RunDiff | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setDiff(null)
    setError(null)
    api
      .get<RunDiff>(`/runs/${runId}/diff`)
      .then((result) => {
        setDiff(result)
        setSelected(result.files[0]?.path ?? null)
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
  }, [api, runId])

  const file = diff?.files.find((f) => f.path === selected) ?? null

  return (
    <div className="diff-view">
      <div className="diff-view__header">
        <span className="diff-view__title">Proposed changes</span>
        <span className="diff-view__note">
          Review only: your workspace is unchanged. Applying changes arrives in milestone M6.
        </span>
        <button type="button" className="icon-button" aria-label="Close diff" title="Close" onClick={onClose}>
          <X size={14} />
        </button>
      </div>
      {error ? (
        <EmptyState title="Could not load the diff">{error}</EmptyState>
      ) : !diff ? (
        <EmptyState title="Loading diff…" />
      ) : diff.files.length === 0 ? (
        <EmptyState title="This run changed no files" />
      ) : (
        <div className="diff-view__body">
          <ul className="diff-files" aria-label="Changed files">
            {diff.files.map((f) => (
              <li key={f.path}>
                <button
                  type="button"
                  className="diff-files__item"
                  aria-current={f.path === selected ? 'true' : undefined}
                  onClick={() => setSelected(f.path)}
                >
                  <span className="diff-files__kind" data-kind={f.change_type}>
                    {CHANGE_LABEL[f.change_type]}
                  </span>
                  {f.path}
                </button>
              </li>
            ))}
          </ul>
          <div className="diff-view__editor">
            {file && (
              <DiffEditor
                key={file.path}
                original={file.original ?? ''}
                modified={file.modified ?? ''}
                originalModelPath={`diff:///${runId}/base/${file.path}`}
                modifiedModelPath={`diff:///${runId}/run/${file.path}`}
                theme={HEX_THEME}
                options={{
                  readOnly: true,
                  originalEditable: false,
                  renderSideBySide: true,
                  minimap: { enabled: false },
                  automaticLayout: true,
                  scrollBeyondLastLine: false,
                  fontSize: 13
                }}
              />
            )}
          </div>
        </div>
      )}
    </div>
  )
}
