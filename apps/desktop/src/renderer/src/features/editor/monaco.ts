import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'
import EditorWorker from 'monaco-editor/editor/editor.worker?worker'
import CssWorker from 'monaco-editor/language/css/css.worker?worker'
import HtmlWorker from 'monaco-editor/language/html/html.worker?worker'
import JsonWorker from 'monaco-editor/language/json/json.worker?worker'
import TsWorker from 'monaco-editor/language/typescript/ts.worker?worker'

// Bundle Monaco locally (the default loader fetches it from a CDN, which the CSP forbids).
self.MonacoEnvironment = {
  getWorker(_workerId: string, label: string) {
    switch (label) {
      case 'json':
        return new JsonWorker()
      case 'css':
      case 'scss':
      case 'less':
        return new CssWorker()
      case 'html':
      case 'handlebars':
      case 'razor':
        return new HtmlWorker()
      case 'typescript':
      case 'javascript':
        return new TsWorker()
      default:
        return new EditorWorker()
    }
  }
}

loader.config({ monaco })

export const HEX_THEME = 'hex-dark'

monaco.editor.defineTheme(HEX_THEME, {
  base: 'vs-dark',
  inherit: true,
  rules: [],
  colors: {
    'editor.background': '#0f1115',
    'editorGutter.background': '#0f1115',
    'editor.lineHighlightBackground': '#151821',
    'editorLineNumber.foreground': '#4b5263',
    'editorLineNumber.activeForeground': '#9aa3b5',
    'editorWidget.background': '#1b1f2a',
    'editorWidget.border': '#2a3040'
  }
})

/** Model URI for a workspace file; scoped by project so two projects never share a model. */
export function modelPath(projectId: string, path: string): string {
  return `file:///${projectId}/${path}`
}

export function disposeModel(projectId: string, path: string): void {
  monaco.editor.getModel(monaco.Uri.parse(modelPath(projectId, path)))?.dispose()
}

export { monaco }
