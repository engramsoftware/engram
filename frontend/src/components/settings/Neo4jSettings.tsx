/**
 * Neo4j Knowledge Graph settings card.
 * Enable switch, URI, username, password, database fields, and a test
 * connection button.
 *
 * @param config - Current Neo4j config from the backend (may be undefined)
 * @param onUpdate - Callback to refresh parent settings after save
 */

import { useState, useEffect } from 'react'
import { Share2 } from 'lucide-react'
import { settingsApi } from '../../services/api'
import type { Neo4jConfig } from '../../types/chat.types'
import { ActionButton, ActionStatus, Badge, InfoNote, SettingsCard, TextField, useAction } from './primitives'

interface Props {
  config?: Neo4jConfig
  onUpdate: () => void
}

export default function Neo4jSettings({ config, onUpdate }: Props) {
  const [isEnabled, setIsEnabled] = useState(config?.enabled || false)
  const [isOpen, setIsOpen] = useState(config?.enabled || false)
  const [uri, setUri] = useState(config?.uri || '')
  const [username, setUsername] = useState(config?.username || 'neo4j')
  const [password, setPassword] = useState('')
  const [database, setDatabase] = useState(config?.database || 'neo4j')
  const [saveState, runSave] = useAction()
  const [testState, runTest] = useAction()
  const [toggleState, runToggle] = useAction()

  // One value per effect, so a refresh only resets a field whose saved value changed
  useEffect(() => { setIsEnabled(config?.enabled || false) }, [config?.enabled])
  useEffect(() => { setUri(config?.uri || '') }, [config?.uri])
  useEffect(() => { setUsername(config?.username || 'neo4j') }, [config?.username])
  useEffect(() => { setDatabase(config?.database || 'neo4j') }, [config?.database])

  const fields = () => ({
    uri: uri || undefined,
    username: username || undefined,
    database,
  })

  // Enabling/disabling saves immediately; the switch reverts if that fails
  const handleToggle = (next: boolean) => {
    setIsEnabled(next)
    if (next) setIsOpen(true)
    runToggle(async () => {
      try {
        await settingsApi.updateLLMSettings({ neo4j: { enabled: next, ...fields() } })
      } catch (error) {
        setIsEnabled(!next)
        throw error
      }
      onUpdate()
    }, next ? 'Knowledge graph enabled' : 'Knowledge graph disabled')
  }

  const handleSave = () => runSave(async () => {
    await settingsApi.updateLLMSettings({
      neo4j: { enabled: isEnabled, ...fields(), password: password || undefined },
    })
    setPassword('')
    onUpdate()
  })

  const handleTest = () => runTest(async () => {
    const result = await settingsApi.testNeo4j(
      uri || undefined,
      username || undefined,
      password || undefined,
      database || undefined,
    )
    if (!result.success) throw new Error(result.error || result.message || 'could not connect')
  }, 'Connected', 'Connection failed')

  return (
    <SettingsCard
      title="Neo4j Knowledge Graph"
      subtitle="Entity relationships and knowledge graph storage"
      icon={<Share2 size={14} />}
      enabled={isEnabled}
      onToggle={handleToggle}
      toggleDisabled={toggleState.status === 'busy'}
      open={isOpen}
      onOpenChange={setIsOpen}
      badges={config?.password_set ? <Badge tone="green">configured</Badge> : undefined}
    >
      <ActionStatus state={toggleState.status === 'error' ? toggleState : { status: 'idle' }} />

      <InfoNote>
        Connect to Neo4j Aura (cloud) or a local Neo4j instance for knowledge graph features.
        Get a free instance at{' '}
        <a
          href="https://neo4j.com/cloud/aura-free/"
          target="_blank"
          rel="noopener noreferrer"
          className="text-dark-accent-primary hover:underline"
        >
          neo4j.com/cloud/aura-free
        </a>
      </InfoNote>

      <TextField label="Connection URI" value={uri} onChange={setUri} placeholder="neo4j+s://xxxxx.databases.neo4j.io" />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <TextField label="Username" value={username} onChange={setUsername} placeholder="neo4j" />
        <TextField label="Database" value={database} onChange={setDatabase} placeholder="neo4j" />
      </div>

      <TextField
        label="Password"
        type="password"
        value={password}
        onChange={setPassword}
        placeholder={config?.password_set ? 'Saved; leave empty to keep it' : 'Enter password'}
        hint={config?.password_set && config.password_masked ? `Current: ${config.password_masked}` : undefined}
      />

      <div className="flex items-center gap-2 flex-wrap pt-1">
        <ActionButton variant="primary" onClick={handleSave} busy={saveState.status === 'busy'}>
          {saveState.status === 'busy' ? 'Saving…' : 'Save'}
        </ActionButton>
        <ActionButton onClick={handleTest} busy={testState.status === 'busy'}>
          {testState.status === 'busy' ? 'Testing…' : 'Test'}
        </ActionButton>
        <ActionStatus state={saveState} />
        <ActionStatus state={testState} />
      </div>
    </SettingsCard>
  )
}
