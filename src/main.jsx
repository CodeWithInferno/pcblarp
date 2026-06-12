import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { ClerkProvider } from '@clerk/clerk-react'
import './index.css'
import App from './App.jsx'
import Dashboard from './Dashboard.jsx'

const clerkKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

function Root() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/app" element={<Dashboard />} />
      </Routes>
    </BrowserRouter>
  )
}

// Wrap in ClerkProvider only when a key is configured, so the app keeps
// working before auth is set up.
const tree = clerkKey ? (
  <ClerkProvider publishableKey={clerkKey} afterSignOutUrl="/">
    <Root />
  </ClerkProvider>
) : (
  <Root />
)

createRoot(document.getElementById('root')).render(<StrictMode>{tree}</StrictMode>)
