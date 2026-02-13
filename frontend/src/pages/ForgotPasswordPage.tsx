/**
 * Forgot password page.
 *
 * Since Engram is a local/LAN-only app, no email verification is needed.
 * The user enters their email and a new password to reset directly.
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { KeyRound, CheckCircle } from 'lucide-react'
import { authApi } from '../services/api'

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (newPassword !== confirmPassword) {
      setError('Passwords do not match')
      return
    }

    setIsLoading(true)
    try {
      await authApi.resetPassword(email, newPassword)
      setSuccess(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reset failed')
    } finally {
      setIsLoading(false)
    }
  }

  if (success) {
    return (
      <div className="min-h-screen bg-dark-bg-primary flex items-center justify-center p-4">
        <div className="w-full max-w-md text-center">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl
                          bg-green-500/20 border border-green-500/30 mb-4">
            <CheckCircle size={32} className="text-green-400" />
          </div>
          <h1 className="text-2xl font-bold text-dark-text-primary mb-2">Password Reset</h1>
          <p className="text-dark-text-secondary mb-6">
            Your password has been updated. You can now log in with your new password.
          </p>
          <Link
            to="/login"
            className="inline-block bg-dark-accent-primary hover:bg-dark-accent-hover
                       px-6 py-2.5 rounded-lg text-white font-medium transition-colors"
          >
            Back to Login
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-dark-bg-primary flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl
                          bg-indigo-500/20 border border-indigo-500/30 mb-4">
            <KeyRound size={32} className="text-indigo-400" />
          </div>
          <h1 className="text-2xl font-bold text-dark-text-primary">Reset Password</h1>
          <p className="text-dark-text-secondary mt-2 text-sm">
            Enter your email and choose a new password.
            Since Engram runs locally, no email verification is needed.
          </p>
        </div>

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
              placeholder="The email you registered with"
              className="w-full bg-dark-bg-secondary border border-dark-border rounded-lg
                         px-4 py-2.5 text-dark-text-primary placeholder-dark-text-secondary/50
                         focus:outline-none focus:border-indigo-500 transition-colors"
            />
          </div>

          <div>
            <label className="block text-sm text-dark-text-secondary mb-1">New Password</label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={8}
              placeholder="At least 8 characters"
              className="w-full bg-dark-bg-secondary border border-dark-border rounded-lg
                         px-4 py-2.5 text-dark-text-primary placeholder-dark-text-secondary/50
                         focus:outline-none focus:border-indigo-500 transition-colors"
            />
          </div>

          <div>
            <label className="block text-sm text-dark-text-secondary mb-1">Confirm Password</label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={8}
              placeholder="Type it again"
              className="w-full bg-dark-bg-secondary border border-dark-border rounded-lg
                         px-4 py-2.5 text-dark-text-primary placeholder-dark-text-secondary/50
                         focus:outline-none focus:border-indigo-500 transition-colors"
            />
          </div>

          <button
            type="submit"
            disabled={isLoading || !email || !newPassword || newPassword.length < 8 || newPassword !== confirmPassword}
            className="w-full bg-indigo-600 hover:bg-indigo-500 py-2.5 rounded-lg text-white
                       font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors mt-2"
          >
            {isLoading ? 'Resetting...' : 'Reset Password'}
          </button>
        </form>

        <p className="mt-6 text-center text-dark-text-secondary text-sm">
          Remember your password?{' '}
          <Link to="/login" className="text-dark-accent-primary hover:underline">
            Back to login
          </Link>
        </p>
      </div>
    </div>
  )
}
