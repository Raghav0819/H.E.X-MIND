import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

import type { BackendConfig } from '../../../preload/api'
import { createApiClient, type ApiClient } from './api'

interface Backend {
  config: BackendConfig
  api: ApiClient
}

const BackendContext = createContext<Backend | null>(null)

/** Loads the backend URL/token from the preload bridge once and provides an API client. */
export function BackendProvider({ children }: { children: ReactNode }) {
  const [backend, setBackend] = useState<Backend | null>(null)

  useEffect(() => {
    let cancelled = false
    void window.hex.getBackend().then((config) => {
      if (!cancelled) setBackend({ config, api: createApiClient(config) })
    })
    return () => {
      cancelled = true
    }
  }, [])

  if (!backend) return null
  return <BackendContext.Provider value={backend}>{children}</BackendContext.Provider>
}

export function useBackend(): Backend {
  const backend = useContext(BackendContext)
  if (!backend) throw new Error('useBackend must be used inside <BackendProvider>')
  return backend
}
