/// <reference types="vite/client" />

import type { HexApi } from '../../preload/api'

declare global {
  interface Window {
    hex: HexApi
  }
}
