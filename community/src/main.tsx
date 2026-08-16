import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { AuthProvider } from './lib/AuthContext'

// HashRouter, not BrowserRouter: GitHub Pages serves static files with no
// server-side rewrite, so a real path like /community/p/<id> 404s on refresh.
// Hash-based routes (/community/#/p/<id>) always resolve to index.html.
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <HashRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </HashRouter>
  </StrictMode>,
)
