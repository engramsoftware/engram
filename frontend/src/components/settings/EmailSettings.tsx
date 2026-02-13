/**
 * Email notification settings card.
 * Collapsible card with enable toggle, SMTP config (Gmail app password),
 * recipient email, and a test button that sends a real test email.
 *
 * @param config - Current email config from the backend (may be undefined)
 * @param onUpdate - Callback to refresh parent settings after save
 */

import { useState, useEffect } from 'react'
import {
  Check, X, Send, ChevronDown, ChevronRight,
  Loader2, Mail,
} from 'lucide-react'
import { settingsApi } from '../../services/api'
import type { EmailConfig } from '../../types/chat.types'

interface Props {
  config?: EmailConfig
  onUpdate: () => void
}

export default function EmailSettings({ config, onUpdate }: Props) {
  const [isEnabled, setIsEnabled] = useState(config?.enabled || false)
  const [isExpanded, setIsExpanded] = useState(config?.enabled || false)
  const [smtpHost, setSmtpHost] = useState(config?.smtp_host || 'smtp.gmail.com')
  const [smtpPort, setSmtpPort] = useState(config?.smtp_port || 587)
  const [username, setUsername] = useState(config?.username || '')
  const [password, setPassword] = useState('')
  const [recipient, setRecipient] = useState(config?.recipient || '')
  const [fromName, setFromName] = useState(config?.from_name || 'Engram')
  const [isSaving, setIsSaving] = useState(false)
  const [isTesting, setIsTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; error?: string } | null>(null)
  const [saveSuccess, setSaveSuccess] = useState(false)

  useEffect(() => {
    setIsEnabled(config?.enabled || false)
    setSmtpHost(config?.smtp_host || 'smtp.gmail.com')
    setSmtpPort(config?.smtp_port || 587)
    setUsername(config?.username || '')
    setRecipient(config?.recipient || '')
    setFromName(config?.from_name || 'Engram')
  }, [config?.enabled, config?.smtp_host, config?.smtp_port, config?.username, config?.recipient, config?.from_name])

  /** Toggle enable/disable and auto-save. */
  const handleToggle = async (e: React.MouseEvent) => {
    e.stopPropagation()
    const next = !isEnabled
    setIsEnabled(next)
    if (next) setIsExpanded(true)
    try {
      await settingsApi.updateLLMSettings({
        email: {
          enabled: next,
          smtp_host: smtpHost,
          smtp_port: smtpPort,
          username: username || undefined,
          recipient: recipient || undefined,
          from_name: fromName,
        },
      })
      onUpdate()
    } catch (error) {
      console.error('Failed to toggle email:', error)
      setIsEnabled(!next)
    }
  }

  /** Save all email settings. */
  const handleSave = async () => {
    setIsSaving(true)
    setSaveSuccess(false)
    try {
      await settingsApi.updateLLMSettings({
        email: {
          enabled: isEnabled,
          smtp_host: smtpHost,
          smtp_port: smtpPort,
          username: username || undefined,
          password: password || undefined,
          recipient: recipient || undefined,
          from_name: fromName,
        },
      })
      setPassword('')
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 2000)
      onUpdate()
    } catch (error) {
      console.error('Failed to save email settings:', error)
    } finally {
      setIsSaving(false)
    }
  }

  /** Send a test email. */
  const handleTest = async () => {
    setIsTesting(true)
    setTestResult(null)
    try {
      const result = await settingsApi.testEmail()
      setTestResult(result)
    } catch {
      setTestResult({ success: false, error: 'Request failed' })
    } finally {
      setIsTesting(false)
    }
  }

  return (
    <div className="rounded-xl border border-dark-border bg-dark-bg-secondary/50 overflow-hidden">
      {/* Header row */}
      <div
        className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-dark-bg-secondary/80 transition-colors"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3 min-w-0">
          <button
            onClick={(e) => { e.stopPropagation(); setIsExpanded(!isExpanded) }}
            className="text-dark-text-secondary"
          >
            {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </button>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Mail size={14} className="text-dark-text-secondary flex-shrink-0" />
              <span className="text-sm font-medium text-dark-text-primary">
                Email Notifications
              </span>
              {config?.password_set && (
                <span className="text-[10px] text-green-400 bg-green-400/10 px-1.5 py-0.5 rounded-full">
                  configured
                </span>
              )}
            </div>
            <p className="text-xs text-dark-text-secondary truncate">
              Engram sends you emails — reminders, summaries, task alerts
            </p>
          </div>
        </div>

        {/* Enable toggle */}
        <button
          onClick={handleToggle}
          className={`relative inline-flex items-center w-10 h-6 rounded-full transition-colors flex-shrink-0 ${
            isEnabled ? 'bg-dark-accent-primary' : 'bg-dark-border'
          }`}
        >
          <span className={`inline-block w-4 h-4 rounded-full bg-white shadow-sm transition-transform ${
            isEnabled ? 'translate-x-5' : 'translate-x-1'
          }`} />
        </button>
      </div>

      {/* Expanded content */}
      {isExpanded && (
        <div className="px-4 pb-4 pt-1 space-y-3 border-t border-dark-border/30">
          {/* Info */}
          <div className="text-xs text-dark-text-secondary bg-dark-bg-primary/60 rounded-md px-3 py-2">
            Use a Gmail App Password (not your real password).{' '}
            <a
              href="https://myaccount.google.com/apppasswords"
              target="_blank"
              rel="noopener noreferrer"
              className="text-dark-accent-primary hover:underline"
            >
              Generate one here
            </a>
            . Engram will email you when it has something to tell you.
          </div>

          {/* Gmail / Username */}
          <div>
            <label className="block text-xs text-dark-text-secondary mb-1">
              Gmail Address
            </label>
            <input
              type="email"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="you@gmail.com"
              className="w-full bg-dark-bg-primary border border-dark-border rounded-md
                         px-3 py-1.5 text-sm text-dark-text-primary placeholder:text-dark-text-secondary/40
                         focus:outline-none focus:border-dark-accent-primary"
            />
          </div>

          {/* App Password */}
          <div>
            <label className="block text-xs text-dark-text-secondary mb-1">
              App Password {config?.password_set && !password && (
                <span className="text-dark-text-secondary/60">
                  ({config.password_masked} — leave empty to keep)
                </span>
              )}
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={config?.password_set ? '••••••••' : '16-char app password'}
              className="w-full bg-dark-bg-primary border border-dark-border rounded-md
                         px-3 py-1.5 text-sm text-dark-text-primary placeholder:text-dark-text-secondary/40
                         focus:outline-none focus:border-dark-accent-primary"
            />
          </div>

          {/* Recipient + From Name */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs text-dark-text-secondary mb-1">
                Send Notifications To
              </label>
              <input
                type="email"
                value={recipient}
                onChange={(e) => setRecipient(e.target.value)}
                placeholder="Same as Gmail if empty"
                className="w-full bg-dark-bg-primary border border-dark-border rounded-md
                           px-3 py-1.5 text-sm text-dark-text-primary placeholder:text-dark-text-secondary/40
                           focus:outline-none focus:border-dark-accent-primary"
              />
            </div>
            <div>
              <label className="block text-xs text-dark-text-secondary mb-1">
                Sender Name
              </label>
              <input
                type="text"
                value={fromName}
                onChange={(e) => setFromName(e.target.value)}
                placeholder="Engram"
                className="w-full bg-dark-bg-primary border border-dark-border rounded-md
                           px-3 py-1.5 text-sm text-dark-text-primary placeholder:text-dark-text-secondary/40
                           focus:outline-none focus:border-dark-accent-primary"
              />
            </div>
          </div>

          {/* Advanced: SMTP host/port (collapsed by default for Gmail users) */}
          <details className="text-xs">
            <summary className="text-dark-text-secondary cursor-pointer hover:text-dark-text-primary transition-colors">
              Advanced SMTP settings
            </summary>
            <div className="grid grid-cols-2 gap-2 mt-2">
              <div>
                <label className="block text-xs text-dark-text-secondary mb-1">SMTP Host</label>
                <input
                  type="text"
                  value={smtpHost}
                  onChange={(e) => setSmtpHost(e.target.value)}
                  className="w-full bg-dark-bg-primary border border-dark-border rounded-md
                             px-3 py-1.5 text-sm text-dark-text-primary
                             focus:outline-none focus:border-dark-accent-primary"
                />
              </div>
              <div>
                <label className="block text-xs text-dark-text-secondary mb-1">SMTP Port</label>
                <input
                  type="number"
                  value={smtpPort}
                  onChange={(e) => setSmtpPort(parseInt(e.target.value) || 587)}
                  className="w-full bg-dark-bg-primary border border-dark-border rounded-md
                             px-3 py-1.5 text-sm text-dark-text-primary
                             focus:outline-none focus:border-dark-accent-primary"
                />
              </div>
            </div>
          </details>

          {/* Actions */}
          <div className="flex items-center gap-2 pt-1">
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium
                         bg-dark-accent-primary hover:bg-dark-accent-hover text-white
                         disabled:opacity-50 transition-colors"
            >
              {isSaving ? (
                <Loader2 size={12} className="animate-spin" />
              ) : saveSuccess ? (
                <Check size={12} />
              ) : null}
              {saveSuccess ? 'Saved' : 'Save'}
            </button>

            <button
              onClick={handleTest}
              disabled={isTesting || !config?.password_set}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium
                         bg-dark-bg-primary border border-dark-border text-dark-text-secondary
                         hover:text-dark-text-primary hover:border-dark-accent-primary
                         disabled:opacity-50 transition-colors"
              title={!config?.password_set ? 'Save settings first' : 'Send a test email'}
            >
              {isTesting ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Send size={12} />
              )}
              Send Test
            </button>

            {testResult !== null && (
              <span className={`flex items-center gap-1 text-xs ${
                testResult.success ? 'text-green-400' : 'text-red-400'
              }`}>
                {testResult.success ? <Check size={12} /> : <X size={12} />}
                {testResult.success ? 'Sent! Check inbox' : testResult.error || 'Failed'}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
