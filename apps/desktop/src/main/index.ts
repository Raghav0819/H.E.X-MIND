import { join } from 'node:path'

import { app, BrowserWindow, ipcMain, shell, type IpcMainInvokeEvent } from 'electron'

import { IPC, type AppInfo, type BackendConfig } from '../preload/api'

/** Set by electron-vite while running `electron-vite dev`. */
const devServerUrl = process.env['ELECTRON_RENDERER_URL']

function loadRootEnv(): void {
  // In development the backend and the desktop app share the repository-root .env.
  // The packaged app will generate a per-session token instead (milestone M8).
  try {
    process.loadEnvFile(join(app.getAppPath(), '..', '..', '.env'))
  } catch {
    // No .env file: the renderer shows a "not configured" state.
  }
}

function backendConfig(): BackendConfig {
  const port = Number(process.env['HEXMIND_PORT'] ?? 8765)
  return { url: `http://127.0.0.1:${port}`, token: process.env['HEXMIND_API_TOKEN'] || null }
}

function isAppUrl(url: string): boolean {
  if (devServerUrl) return url.startsWith(devServerUrl)
  return url.startsWith('file://')
}

/** Only our own renderer may call privileged IPC handlers. */
function assertTrustedSender(event: IpcMainInvokeEvent): void {
  const url = event.senderFrame?.url ?? ''
  if (!isAppUrl(url)) throw new Error(`Rejected IPC from untrusted frame: ${url}`)
}

function registerIpc(): void {
  ipcMain.handle(IPC.getBackend, (event) => {
    assertTrustedSender(event)
    return backendConfig()
  })
  ipcMain.handle(IPC.appInfo, (event): AppInfo => {
    assertTrustedSender(event)
    return { version: app.getVersion(), platform: process.platform }
  })
}

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 960,
    minHeight: 600,
    show: false,
    title: 'H.E.X Mind',
    backgroundColor: '#0f1115',
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  })

  win.once('ready-to-show', () => win.show())

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://')) void shell.openExternal(url)
    return { action: 'deny' }
  })
  win.webContents.on('will-navigate', (event, url) => {
    if (!isAppUrl(url)) event.preventDefault()
  })

  if (devServerUrl) {
    void win.loadURL(devServerUrl)
  } else {
    void win.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

loadRootEnv()

app.whenReady().then(() => {
  registerIpc()
  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
