/**
 * Login page component.
 */

import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuthStore } from '../stores/authStore'
import { authApi } from '../services/api'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  
  const { login } = useAuthStore()
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setIsLoading(true)

    try {
      const data = await authApi.login(email, password)
      login(data.access_token, data.user)
      navigate('/')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-dark-bg-primary flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <h1 className="text-3xl font-bold text-dark-text-primary text-center mb-8">
          Welcome Back
        </h1>
        
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="p-3 bg-red-500/10 border border-red-500/50 rounded-lg text-red-400 text-sm">
              {error}
            </div>
          )}
          
          <div>
            <label className="block text-sm text-dark-text-secondary mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              className="w-full bg-dark-bg-secondary border border-dark-border rounded-lg
                         px-4 py-2 text-dark-text-primary focus:outline-none focus:border-dark-accent-primary"
            />
          </div>
          
          <div>
            <label className="block text-sm text-dark-text-secondary mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className="w-full bg-dark-bg-secondary border border-dark-border rounded-lg
                         px-4 py-2 text-dark-text-primary focus:outline-none focus:border-dark-accent-primary"
            />
          </div>
          
          <button
            type="submit"
            disabled={isLoading}
            className="w-full bg-dark-accent-primary hover:bg-dark-accent-hover
                       py-2 rounded-lg text-white font-medium disabled:opacity-50"
          >
            {isLoading ? 'Signing in...' : 'Sign In'}
          </button>
        </form>
        
        <div className="mt-6 text-center space-y-2">
          <p className="text-dark-text-secondary">
            Don't have an account?{' '}
            <Link to="/register" className="text-dark-accent-primary hover:underline">
              Sign up
            </Link>
          </p>
          <p>
            <Link to="/forgot-password" className="text-sm text-dark-text-secondary hover:text-dark-accent-primary transition-colors">
              Forgot your password?
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}
