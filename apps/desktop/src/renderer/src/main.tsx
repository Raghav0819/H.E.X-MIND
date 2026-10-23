import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'
import { BackendProvider } from './lib/backend'
import './styles/tokens.css'
import './styles/app.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BackendProvider>
      <App />
    </BackendProvider>
  </StrictMode>
)
