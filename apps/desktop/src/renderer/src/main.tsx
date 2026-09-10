import '@fontsource-variable/geist-mono'
import '@fontsource-variable/instrument-sans'
import '@fontsource-variable/newsreader'
import './assets/main.css'

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { ErrorBoundary } from './components/error-boundary'

// Apply before React mounts, including the first transparent native frame.
document.documentElement.dataset.surface =
  new URLSearchParams(window.location.search).get('surface') === 'island' ? 'island' : 'main'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>
)
