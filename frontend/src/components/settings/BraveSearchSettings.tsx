/**
 * Web search (Brave Search) card.
 * The switch saves at once (with a key typed in the field); the key itself
 * is a draft until Save.
 *
 * @param config - Current Brave Search configuration from the backend
 * @param onUpdate - Callback to refresh parent settings after save
 */

import { useState, useEffect } from 'react'
import { Globe } from 'lucide-react'
import { settingsApi } from '../../services/api'
import type { BraveSearchConfig } from '../../types/chat.types'
import {
  ActionButton, ActionRow, ActionStatus, ErrorStatus, InfoNote, PasswordField, SettingsCard,
  useAction, useDirty, type CardStatus,
} from './primitives'

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

  const dirty = apiKey !== ''
  useDirty(dirty)

  const save = (enabled: boolean) => settingsApi.updateLLMSettings({
    brave_search: { enabled, api_key: apiKey || undefined },
  })

  // The switch saves at once, including a key typed in the field; it reverts if that fails
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
      setApiKey('')
      onUpdate()
    }, next ? 'Web search turned on' : 'Web search turned off', "Couldn't change web search")
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

  const status: CardStatus = !isEnabled ? 'off' : config?.api_key_set ? 'on' : 'needs-setup'

  return (
    <SettingsCard
      title="Web search"
      subtitle="Uses Brave Search for current information. Free key: 2,000 searches a month."
      meta={config?.api_key_set ? `Key saved · ${config.api_key_masked ?? ''}` : 'No API key saved'}
      icon={<Globe size={14} />}
      status={status}
      unsaved={dirty}
      enabled={isEnabled}
      onToggle={handleToggle}
      toggleLabel="Web search"
      toggleDisabled={toggleState.status === 'busy'}
      open={isOpen}
      onOpenChange={setIsOpen}
    >
      <ErrorStatus state={toggleState} />

      <InfoNote>
        Get a free API key at{' '}
        <a
          href="https://api-dashboard.search.brave.com/app/keys"
          target="_blank"
          rel="noopener noreferrer"
          className="text-dark-accent-text hover:underline"
        >
          api-dashboard.search.brave.com
        </a>
        . Free tier: 2,000 queries a month, 1 query a second.
      </InfoNote>

      <PasswordField
        label="API key"
        value={apiKey}
        onChange={setApiKey}
        placeholder={config?.api_key_set ? 'Paste a new key to replace it' : 'BSA...'}
        hint={config?.api_key_set ? `Key saved · ${config.api_key_masked ?? ''}. Leave empty to keep it.` : undefined}
      />

      <ActionRow>
        <ActionButton onClick={handleTest} busy={testState.status === 'busy'}>
          {testState.status === 'busy' ? 'Testing…' : 'Test'}
        </ActionButton>
        <ActionButton variant="primary" onClick={handleSave} busy={saveState.status === 'busy'} disabled={!dirty}>
          {saveState.status === 'busy' ? 'Saving…' : 'Save'}
        </ActionButton>
        <ActionStatus state={testState} />
        <ActionStatus state={saveState} />
      </ActionRow>
    </SettingsCard>
  )
}
