/**
 * Main App component.
 * Sets up routing and global layout.
 *
 * On first run (no users in database), redirects to the onboarding wizard.
 * After setup, shows login/register or the main chat interface.
 */

import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './stores/authStore'
import Layout from './components/layout/Layout'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import SetupPage from './pages/SetupPage'
import ForgotPasswordPage from './pages/ForgotPasswordPage'

function App() {
  const { isAuthenticated } = useAuthStore()
  const [needsSetup, setNeedsSetup] = useState<boolean | null>(null)

  // Check if this is a first-run (no users exist)
  useEffect(() => {
    fetch('/api/setup/status')
      .then(r => r.json())
      .then(data => setNeedsSetup(data.needsSetup))
      .catch(() => setNeedsSetup(false))
  }, [])

  // Show nothing while checking setup status (prevents flash)
  if (needsSetup === null) {
    return (
      <div className="min-h-screen bg-dark-bg-primary flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <BrowserRouter>
      <Routes>
        {/* First-run onboarding wizard */}
        <Route
          path="/setup"
          element={<SetupPage />}
        />

        {/* Public routes */}
        <Route 
          path="/login" 
          element={isAuthenticated ? <Navigate to="/" /> : needsSetup ? <Navigate to="/setup" /> : <LoginPage />} 
        />
        <Route 
          path="/register" 
          element={isAuthenticated ? <Navigate to="/" /> : <RegisterPage />} 
        />
        <Route
          path="/forgot-password"
          element={isAuthenticated ? <Navigate to="/" /> : <ForgotPasswordPage />}
        />
        
        {/* Protected routes — redirect to setup if first run */}
        <Route 
          path="/*" 
          element={
            needsSetup && !isAuthenticated
              ? <Navigate to="/setup" />
              : isAuthenticated
                ? <Layout />
                : <Navigate to="/login" />
          } 
        />
      </Routes>
    </BrowserRouter>
  )
}

export default App
