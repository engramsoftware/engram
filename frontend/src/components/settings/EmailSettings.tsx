/**
 * Email notification settings card.
 * Enable switch, SMTP config (Gmail app password), recipient email, and a
 * test button that sends a real test email.
 *
 * @param config - Current email config from the backend (may be undefined)
 * @param onUpdate - Callback to refresh parent settings after save
 */

import { useState, useEffect } from 'react'
import { Mail, Send } from 'lucide-react'
import { settingsApi } from '../../services/api'
import type { EmailConfig } from '../../types/chat.types'
import { ActionButton, ActionStatus, Badge, InfoNote, SettingsCard, TextField, useAction } from './primitives'

interface Props {
  config?: EmailConfig
  onUpdate: () => void
}

export default function EmailSettings({ config, onUpdate }: Props) {
  const [isEnabled, setIsEnabled] = useState(config?.enabled || false)
  const [isOpen, setIsOpen] = useState(config?.enabled || false)
  const [smtpHost, setSmtpHost] = useState(config?.smtp_host || 'smtp.gmail.com')
  const [smtpPort, setSmtpPort] = useState(String(config?.smtp_port || 587))
  const [username, setUsername] = useState(config?.username || '')
  const [password, setPassword] = useState('')
  const [recipient, setRecipient] = useState(config?.recipient || '')
  const [fromName, setFromName] = useState(config?.from_name || 'Engram')
  const [saveState, runSave] = useAction()
  const [testState, runTest] = useAction()
  const [toggleState, runToggle] = useAction()

  // One value per effect, so a refresh only resets a field whose saved value changed
  useEffect(() => { setIsEnabled(config?.enabled || false) }, [config?.enabled])
  useEffect(() => { setSmtpHost(config?.smtp_host || 'smtp.gmail.com') }, [config?.smtp_host])
  useEffect(() => { setSmtpPort(String(config?.smtp_port || 587)) }, [config?.smtp_port])
  useEffect(() => { setUsername(config?.username || '') }, [config?.username])
  useEffect(() => { setRecipient(config?.recipient || '') }, [config?.recipient])
  useEffect(() => { setFromName(config?.from_name || 'Engram') }, [config?.from_name])

  const fields = () => ({
    smtp_host: smtpHost,
    smtp_port: parseInt(smtpPort, 10) || 587,
    username: username || undefined,
    recipient: recipient || undefined,
    from_name: fromName,
  })

  // Enabling/disabling saves immediately; the switch reverts if that fails
  const handleToggle = (next: boolean) => {
    setIsEnabled(next)
    if (next) setIsOpen(true)
    runToggle(async () => {
      try {
        await settingsApi.updateLLMSettings({ email: { enabled: next, ...fields() } })
      } catch (error) {
        setIsEnabled(!next)
        throw error
      }
      onUpdate()
    }, next ? 'Email notifications enabled' : 'Email notifications disabled')
  }

  const handleSave = () => runSave(async () => {
    await settingsApi.updateLLMSettings({
      email: { enabled: isEnabled, ...fields(), password: password || undefined },
    })
    setPassword('')
    onUpdate()
  })

  const handleTest = () => runTest(async () => {
    const result = await settingsApi.testEmail()
    if (!result.success) throw new Error(result.error || 'the server rejected the message')
  }, 'Sent. Check your inbox', 'Test email failed')

  return (
    <SettingsCard
      title="Email Notifications"
      subtitle="Engram sends you emails: reminders, summaries, task alerts"
      icon={<Mail size={14} />}
      enabled={isEnabled}
      onToggle={handleToggle}
      toggleDisabled={toggleState.status === 'busy'}
      open={isOpen}
      onOpenChange={setIsOpen}
      badges={config?.password_set ? <Badge tone="green">configured</Badge> : undefined}
    >
      <ActionStatus state={toggleState.status === 'error' ? toggleState : { status: 'idle' }} />

      <InfoNote>
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
      </InfoNote>

      <TextField label="Gmail address" type="email" value={username} onChange={setUsername} placeholder="you@gmail.com" autoComplete="off" />

      <TextField
        label="App password"
        type="password"
        value={password}
        onChange={setPassword}
        placeholder={config?.password_set ? 'Saved; leave empty to keep it' : '16-character app password'}
        hint={config?.password_set && config.password_masked ? `Current: ${config.password_masked}` : undefined}
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <TextField label="Send notifications to" type="email" value={recipient} onChange={setRecipient} placeholder="Same as Gmail if empty" />
        <TextField label="Sender name" value={fromName} onChange={setFromName} placeholder="Engram" />
      </div>

      {/* Advanced: SMTP host/port (collapsed by default for Gmail users) */}
      <details className="text-xs">
        <summary className="text-dark-text-secondary cursor-pointer hover:text-dark-text-primary transition-colors">
          Advanced SMTP settings
        </summary>
        <div className="grid grid-cols-2 gap-2 mt-2">
          <TextField label="SMTP host" value={smtpHost} onChange={setSmtpHost} />
          <TextField label="SMTP port" type="number" value={smtpPort} onChange={setSmtpPort} />
        </div>
      </details>

      <div className="flex items-center gap-2 flex-wrap pt-1">
        <ActionButton variant="primary" onClick={handleSave} busy={saveState.status === 'busy'}>
          {saveState.status === 'busy' ? 'Saving…' : 'Save'}
        </ActionButton>
        <ActionButton
          onClick={handleTest}
          busy={testState.status === 'busy'}
          disabled={!config?.password_set}
          title={!config?.password_set ? 'Save an app password first' : 'Send a test email'}
        >
          {testState.status !== 'busy' && <Send size={12} />}
          Send test
        </ActionButton>
        <ActionStatus state={saveState} />
        <ActionStatus state={testState} />
      </div>
    </SettingsCard>
  )
}
