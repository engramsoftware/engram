/**
 * Brave Search API settings card.
 * Allows users to configure their Brave Search API key for web search.
 *
 * @param config - Current Brave Search configuration from the backend
 * @param onUpdate - Callback to refresh parent settings after save
 */

import { useState, useEffect } from 'react'
import { Globe, Zap } from 'lucide-react'
import { settingsApi } from '../../services/api'
import type { BraveSearchConfig } from '../../types/chat.types'
import { ActionButton, ActionStatus, Badge, InfoNote, SettingsCard, TextField, useAction } from './primitives'

interface Props {
  config?: BraveSearchConfig
  onUpdate: () => void
}

export default function BraveSearchSettings({ config, onUpdate }: Props) {
  const [apiKey, setApiKey] = useState('')
  const [isEnabled, setIsEnabled] = useState(config?.enabled || false)
  const [isOpen, setIsOpen] = useState(config?.enabled || false)
  const [saveState, runSave] = useAction()
  const [testState, runTest, resetTest] = useAction({ sticky: true })
  // A test result describes the values it was run with; editing them clears it
  useEffect(() => { resetTest() }, [apiKey, resetTest])
  const [toggleState, runToggle] = useAction()

  useEffect(() => { setIsEnabled(config?.enabled || false) }, [config?.enabled])

  const save = (enabled: boolean) => settingsApi.updateLLMSettings({
    brave_search: { enabled, api_key: apiKey || undefined },
  })

  // Enabling/disabling saves immediately; the switch reverts if that fails
  const handleToggle = (next: boolean) => {
    setIsEnabled(next)
    if (next) setIsOpen(true)
    runToggle(async () => {
      try {
        await save(next)
      } catch (error) {
        setIsEnabled(!next)
        throw error
      }
      onUpdate()
    }, next ? 'Web search enabled' : 'Web search disabled')
  }

  const handleSave = () => runSave(async () => {
    await save(isEnabled)
    setApiKey('')
    onUpdate()
  })

  const handleTest = () => runTest(async () => {
    const result = await settingsApi.testBraveSearch(apiKey || undefined)
    if (!result.success) throw new Error(result.error || result.message || 'the key was rejected')
  }, 'Connected', 'Test failed')

  return (
    <SettingsCard
      title="Brave Search"
      subtitle="Web search for real-time info (free tier: 1 req/sec)"
      icon={<Globe size={14} />}
      enabled={isEnabled}
      onToggle={handleToggle}
      toggleDisabled={toggleState.status === 'busy'}
      open={isOpen}
      onOpenChange={setIsOpen}
      badges={isEnabled ? <Badge tone="green"><Zap size={8} /> Active</Badge> : undefined}
    >
      <ActionStatus state={toggleState.status === 'error' ? toggleState : { status: 'idle' }} />

      <InfoNote>
        Get a free API key at{' '}
        <a
          href="https://api-dashboard.search.brave.com/app/keys"
          target="_blank"
          rel="noopener noreferrer"
          className="text-dark-accent-primary hover:underline"
        >
          api-dashboard.search.brave.com
        </a>
        . Free tier: 2,000 queries/month, 1 query/second.
      </InfoNote>

      <TextField
        label="API key"
        type="password"
        value={apiKey}
        onChange={setApiKey}
        placeholder={config?.api_key_set ? 'Saved; leave empty to keep it' : 'BSA...'}
        hint={config?.api_key_masked ? `Current: ${config.api_key_masked}` : undefined}
      />

      <div className="flex items-center gap-2 flex-wrap pt-1">
        <ActionButton onClick={handleTest} busy={testState.status === 'busy'}>
          {testState.status === 'busy' ? 'Testing…' : 'Test'}
        </ActionButton>
        <ActionButton variant="primary" onClick={handleSave} busy={saveState.status === 'busy'}>
          {saveState.status === 'busy' ? 'Saving…' : 'Save'}
        </ActionButton>
        <ActionStatus state={testState} />
        <ActionStatus state={saveState} />
      </div>
    </SettingsCard>
  )
}
