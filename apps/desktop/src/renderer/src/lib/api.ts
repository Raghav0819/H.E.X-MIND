import type { BackendConfig } from '../../../preload/api'

// ---------- Backend response types (mirror apps/backend/app/api/schemas.py) ----------

export interface ProviderHealth {
  provider: string
  available: boolean
  model: string
  detail: string | null
}

export interface HealthInfo {
  status: 'ok'
  version: string
  db: 'ok' | 'unavailable'
  providers: Record<string, ProviderHealth>
}

export interface Project {
  id: string
  name: string
  workspace_path: string
  git_enabled: boolean
  created_at: string
  updated_at: string
}

export interface TreeEntry {
  name: string
  path: string
  type: 'file' | 'directory'
  size: number | null
}

export interface FileContent {
  path: string
  content: string | null
  hash: string
  size: number
  binary: boolean
  too_large: boolean
}

export interface FileWritten {
  path: string
  hash: string
}

// ---------- Client ----------

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly body: unknown
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

type Query = Record<string, string | undefined>

export interface ApiClient {
  get<T>(path: string, query?: Query): Promise<T>
  post<T>(path: string, body?: unknown): Promise<T>
  put<T>(path: string, body: unknown): Promise<T>
}

export function createApiClient(config: BackendConfig, fetchFn: typeof fetch = fetch): ApiClient {
  async function request<T>(method: string, path: string, body?: unknown, query?: Query): Promise<T> {
    const url = new URL(`/api${path}`, config.url)
    for (const [key, value] of Object.entries(query ?? {})) {
      if (value !== undefined) url.searchParams.set(key, value)
    }
    const headers: Record<string, string> = {}
    if (config.token) headers['Authorization'] = `Bearer ${config.token}`
    if (body !== undefined) headers['Content-Type'] = 'application/json'

    const response = await fetchFn(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body)
    })
    const text = await response.text()
    const data: unknown = text ? JSON.parse(text) : null
    if (!response.ok) {
      const detail = (data as { detail?: unknown } | null)?.detail
      throw new ApiError(
        response.status,
        typeof detail === 'string' ? detail : `HTTP ${response.status}`,
        data
      )
    }
    return data as T
  }

  return {
    get: (path, query) => request('GET', path, undefined, query),
    post: (path, body) => request('POST', path, body),
    put: (path, body) => request('PUT', path, body)
  }
}

// ---------- Conversations and runs ----------

export type ChatMode = 'ask' | 'edit' | 'auto'

export interface Conversation {
  id: string
  project_id: string
  title: string
  summary: string | null
  created_at: string
  updated_at: string
}

export interface RouteInfo {
  route: 'answer' | 'clarify' | 'run'
  request_type: string
  complexity: 'low' | 'medium' | 'high'
  confidence: number | null
  strategy: string | null
  fallback_used: boolean
  policy_note: string | null
  reason: string
  decision_id: string
}

export interface ContextSources {
  files: { path: string; reason: 'mentioned' | 'prior_run' | 'search'; truncated: boolean }[]
  omitted_files: string[]
  messages: number
  summary: boolean
  prior_runs: number
}

export interface LlmInfo {
  provider: string
  model: string
  latency_ms: number
  input_tokens: number | null
  output_tokens: number | null
}

export interface AssistantMetadata {
  kind: 'answer' | 'clarification' | 'run_started' | 'error'
  route: RouteInfo
  context: ContextSources
  llm: LlmInfo | null
  run_id: string | null
}

export interface ChatMessage {
  id: string
  conversation_id: string
  role: 'user' | 'assistant' | 'system'
  mode: ChatMode | null
  content: string
  metadata: Partial<AssistantMetadata>
  created_at: string
}

export interface MessageExchange {
  user_message: ChatMessage
  assistant_message: ChatMessage
  run_id: string | null
}

export interface Run {
  id: string
  project_id: string
  conversation_id: string | null
  parent_run_id: string | null
  triggering_message_id: string | null
  title: string
  status: string
  complexity: string | null
  strategy: string | null
  last_event_seq: number
  created_at: string
  started_at: string | null
  finished_at: string | null
}

/** Run statuses after which no further events are expected. */
export const TERMINAL_RUN_STATUSES = new Set(['completed', 'failed', 'cancelled', 'applied', 'rejected', 'reverted'])
