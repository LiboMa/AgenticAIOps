import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
// Use PagerDuty-inspired enterprise App
import App from './AppPagerDuty.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
