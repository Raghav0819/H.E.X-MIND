/** Contract between the preload bridge and the renderer. Keep this surface small and allowlisted. */

export interface BackendConfig {
  url: string
  /** Null when no token is configured; the renderer reports this instead of calling the backend. */
  token: string | null
}

export interface AppInfo {
  version: string
  platform: string
}

export interface HexApi {
  getBackend(): Promise<BackendConfig>
  appInfo(): Promise<AppInfo>
}

export const IPC = {
  getBackend: 'hex:get-backend',
  appInfo: 'hex:app-info'
} as const
