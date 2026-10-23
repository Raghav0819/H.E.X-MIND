import { contextBridge, ipcRenderer } from 'electron'

import { IPC, type HexApi } from './api'

const api: HexApi = {
  getBackend: () => ipcRenderer.invoke(IPC.getBackend),
  appInfo: () => ipcRenderer.invoke(IPC.appInfo)
}

contextBridge.exposeInMainWorld('hex', api)
