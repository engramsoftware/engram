/**
 * Send-email card (the only card in Settings > Email, so it starts open).
 * The switch saves at once (with a password typed in the field); the
 * address, password, recipient, sender name and SMTP server are drafts until Save.
 *
 * @param config - Current email config from the backend (may be undefined)
 * @param onUpdate - Callback to refresh parent settings after save
 */

import { useState, useEffect } from 'react'
import { Mail, Send } from 'lucide-react'
import { settingsApi } from '../../services/api'
import type { EmailConfig } from '../../types/chat.types'
import {
  ActionButton, ActionRow, ActionStatus, Disclosure, ErrorStatus, PasswordField, SettingsCard, TextField,
  useAction, useDirty, type CardStatus,
} from './primitives'

interface Props {
  config?: EmailConfig
  onUpdate: () => void
}

export default function EmailSettings({ config, onUpdate }: Props) {
  const saved = {
    smtpHost: config?.smtp_host || 'smtp.gmail.com',
    smtpPort: String(config?.smtp_port || 587),
    username: config?.username || '',
    recipient: config?.recipient || '',
    fromName: config?.from_name || 'Engram',
  }
  const [isEnabled, setIsEnabled] = useState(config?.enabled || false)
  const [smtpHost, setSmtpHost] = useState(saved.smtpHost)
  const [smtpPort, setSmtpPort] = useState(saved.smtpPort)
  const [username, setUsername] = useState(saved.username)
  const [password, setPassword] = useState('')
  const [recipient, setRecipient] = useState(saved.recipient)
  const [fromName, setFromName] = useState(saved.fromName)
  const [saveState, runSave] = useAction()
  const [testState, runTest, resetTest] = useAction({ sticky: true })
  const [toggleState, runToggle] = useAction()

  // One value per effect, so a refresh only resets a field whose saved value changed
  useEffect(() => { setIsEnabled(config?.enabled || false) }, [config?.enabled])
  useEffect(() => { setSmtpHost(saved.smtpHost) }, [saved.smtpHost])
  useEffect(() => { setSmtpPort(saved.smtpPort) }, [saved.smtpPort])
  useEffect(() => { setUsername(saved.username) }, [saved.username])
  useEffect(() => { setRecipient(saved.recipient) }, [saved.recipient])
  useEffect(() => { setFromName(saved.fromName) }, [saved.fromName])
  // The test sends with the saved settings; a result is stale once they change
  useEffect(() => { resetTest() }, [config?.password_set, saved.username, saved.recipient, saved.smtpHost, saved.smtpPort, resetTest])

  // The backend keeps the saved address and recipient when they arrive empty, so an
  // emptied field is not a change (and is restored after saving)
  const changed = (value: string, savedValue: string) => value !== savedValue && value !== ''
  const dirty = smtpHost !== saved.smtpHost || smtpPort !== saved.smtpPort || changed(username, saved.username)
    || changed(recipient, saved.recipient) || fromName !== saved.fromName || password !== ''
  useDirty(dirty)
  const restoreKept = () => {
    if (!username) setUsername(saved.username)
    if (!recipient) setRecipient(saved.recipient)
  }

  const fields = () => ({
    smtp_host: smtpHost,
    smtp_port: parseInt(smtpPort, 10) || 587,
    username: username || undefined,
    recipient: recipient || undefined,
    from_name: fromName,
    password: password || undefined,
  })

  // The switch saves at once, including what was typed; it reverts if that fails
  const handleToggle = (next: boolean) => {
    setIsEnabled(next)
    runToggle(async () => {
      try {
        await settingsApi.updateLLMSettings({ email: { enabled: next, ...fields() } })
      } catch (error) {
        setIsEnabled(!next)
        throw error
      }
      setPassword('')
      restoreKept()
      onUpdate()
    }, next ? 'Email turned on' : 'Email turned off', "Couldn't change email")
  }

  const handleSave = () => runSave(async () => {
    await settingsApi.updateLLMSettings({ email: { enabled: isEnabled, ...fields() } })
    setPassword('')
    restoreKept()
    onUpdate()
  })

  const handleTest = () => runTest(async () => {
    const result = await settingsApi.testEmail()
    if (!result.success) throw new Error(result.error || 'the server rejected the message')
  }, 'Sent. Check your inbox', 'Test email failed')

  const status: CardStatus = !isEnabled ? 'off' : config?.password_set ? 'on' : 'needs-setup'

  return (
    <SettingsCard
      title="Send email"
      subtitle="Reminders, summaries and alerts, sent through your email account."
      meta={config?.password_set ? 'App password saved' : 'No app password saved'}
      icon={<Mail size={14} />}
      status={status}
      unsaved={dirty}
      enabled={isEnabled}
      onToggle={handleToggle}
      toggleLabel="Send email"
      toggleDisabled={toggleState.status === 'busy'}
      defaultOpen
    >
      <ErrorStatus state={toggleState} />

      <TextField
        label="Email address"
        type="email"
        value={username}
        onChange={setUsername}
        placeholder="you@gmail.com"
        autoComplete="off"
        hint={`Gmail by default. For another provider, change the mail server under Advanced.${
          saved.username ? ' Leave empty to keep the saved address.' : ''}`}
      />

      <PasswordField
        label="App password"
        value={password}
        onChange={setPassword}
        placeholder={config?.password_set ? 'Type a new app password to replace it' : '16-character app password'}
        hint={<>
          Use a Gmail app password, not your normal password.{' '}
          <a
            href="https://myaccount.google.com/apppasswords"
            target="_blank"
            rel="noopener noreferrer"
            className="text-dark-accent-text hover:underline"
          >
            Get one
          </a>
          {config?.password_set && '. A password is saved; leave empty to keep it.'}
        </>}
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <TextField
          label="Send to"
          type="email"
          value={recipient}
          onChange={setRecipient}
          placeholder={saved.recipient ? 'Leave empty to keep it' : 'Your email address if empty'}
          hint={saved.recipient ? 'To send to your own address, type it here.' : undefined}
        />
        <TextField label="Sender name" value={fromName} onChange={setFromName} placeholder="Engram" />
      </div>

      <Disclosure summary="Advanced: mail server (SMTP)">
        <div className="grid grid-cols-2 gap-2">
          <TextField label="SMTP host" value={smtpHost} onChange={setSmtpHost} />
          <TextField label="SMTP port" type="number" value={smtpPort} onChange={setSmtpPort} />
        </div>
      </Disclosure>

      <ActionRow>
        <ActionButton onClick={handleTest} busy={testState.status === 'busy'} disabled={!config?.password_set}>
          {testState.status !== 'busy' && <Send size={12} />}
          Send test email
        </ActionButton>
        <ActionButton variant="primary" onClick={handleSave} busy={saveState.status === 'busy'} disabled={!dirty}>
          {saveState.status === 'busy' ? 'Saving…' : 'Save'}
        </ActionButton>
        <ActionStatus state={testState} />
        <ActionStatus state={saveState} />
      </ActionRow>
      {!config?.password_set ? (
        <p className="text-[11px] text-dark-text-secondary">Save an app password first to send a test email.</p>
      ) : dirty && (
        <p className="text-[11px] text-dark-text-secondary">The test email uses your saved settings; Save first to test your changes.</p>
      )}
    </SettingsCard>
  )
}
