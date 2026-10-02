/**
 * Forgot password page.
 *
 * There is no self-service reset: it let anyone on the network take over an
 * account by typing its email. An admin resets the password in
 * Settings > Users; a locked-out sole admin runs a command on the server.
 */

import { Link } from 'react-router-dom'
import { KeyRound } from 'lucide-react'

const code = 'block w-full overflow-x-auto rounded-md bg-dark-bg-secondary border border-dark-border px-3 py-2 text-xs font-mono text-dark-text-primary'

export default function ForgotPasswordPage() {
  return (
    <div className="min-h-screen bg-dark-bg-primary flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl
                          bg-indigo-500/20 border border-indigo-500/30 mb-4">
            <KeyRound size={32} className="text-indigo-400" />
          </div>
          <h1 className="text-2xl font-bold text-dark-text-primary">Forgot your password?</h1>
        </div>

        <div className="space-y-4 text-sm text-dark-text-secondary">
          <p>
            Ask an admin of this Engram to set a new one for you in{' '}
            <span className="text-dark-text-primary">Settings › Users</span>.
          </p>
          <div className="space-y-2">
            <p>If you're the only admin, run this on the computer that runs Engram:</p>
            <code className={code}>docker exec -it engram python reset_password.py you@example.com</code>
            <p className="text-xs">
              Without Docker, run <code className="font-mono">python reset_password.py you@example.com</code> in
              Engram's backend folder. Add <code className="font-mono">--make-admin</code> to also make the account an admin.
            </p>
          </div>
        </div>

        <p className="mt-6 text-center text-sm">
          <Link to="/login" className="text-dark-accent-text hover:underline">Back to sign in</Link>
        </p>
      </div>
    </div>
  )
}
