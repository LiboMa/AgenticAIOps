import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
// v2: Agent-First Architecture
import App from './AppPagerDuty.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
