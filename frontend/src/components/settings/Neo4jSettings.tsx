/**
 * Knowledge graph (Neo4j) card.
 * The switch saves at once (with a password typed in the field); URI,
 * username, database and password are drafts until Save.
 *
 * These saved settings are used by the Knowledge Graph page and the Test
 * button. Chat reads the server's NEO4J_* values from .env instead, so the
 * card says so rather than implying it controls chat.
 *
 * @param config - Current Neo4j config from the backend (may be undefined)
 * @param onUpdate - Callback to refresh parent settings after save
 */

import { useState, useEffect } from 'react'
import { Share2 } from 'lucide-react'
import { settingsApi } from '../../services/api'
import type { Neo4jConfig } from '../../types/chat.types'
import {
  ActionButton, ActionRow, ActionStatus, ErrorStatus, InfoNote, PasswordField, SettingsCard, TextField,
  useAction, useDirty, type CardStatus,
} from './primitives'

interface Props {
  config?: Neo4jConfig
  onUpdate: () => void
}

export default function Neo4jSettings({ config, onUpdate }: Props) {
  const savedUri = config?.uri || ''
  const savedUsername = config?.username || 'neo4j'
  const savedDatabase = config?.database || 'neo4j'
  const [isEnabled, setIsEnabled] = useState(config?.enabled || false)
  const [isOpen, setIsOpen] = useState(config?.enabled || false)
  const [uri, setUri] = useState(savedUri)
  const [username, setUsername] = useState(savedUsername)
  const [password, setPassword] = useState('')
  const [database, setDatabase] = useState(savedDatabase)
  const [saveState, runSave] = useAction()
  const [testState, runTest, resetTest] = useAction({ sticky: true })
  // A test result describes the values it was run with; editing them clears it
  useEffect(() => { resetTest() }, [uri, username, password, database, resetTest])
  const [toggleState, runToggle] = useAction()

  // One value per effect, so a refresh only resets a field whose saved value changed
  useEffect(() => { setIsEnabled(config?.enabled || false) }, [config?.enabled])
  useEffect(() => { setUri(savedUri) }, [savedUri])
  useEffect(() => { setUsername(savedUsername) }, [savedUsername])
  useEffect(() => { setDatabase(savedDatabase) }, [savedDatabase])

  // The backend keeps the saved URI and username when they arrive empty, so an
  // emptied field is not a change (and is restored after saving)
  const changed = (value: string, savedValue: string) => value !== savedValue && value !== ''
  const dirty = changed(uri, savedUri) || changed(username, savedUsername) || database !== savedDatabase || password !== ''
  useDirty(dirty)
  const restoreKept = () => {
    if (!uri) setUri(savedUri)
    if (!username) setUsername(savedUsername)
  }

  const fields = () => ({
    uri: uri || undefined,
    username: username || undefined,
    database,
    password: password || undefined,
  })

  // The switch saves at once, including what was typed; it reverts if that fails
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
      setPassword('')
      restoreKept()
      onUpdate()
    }, next ? 'Knowledge graph turned on' : 'Knowledge graph turned off', "Couldn't change the knowledge graph")
  }

  const handleSave = () => runSave(async () => {
    await settingsApi.updateLLMSettings({ neo4j: { enabled: isEnabled, ...fields() } })
    setPassword('')
    restoreKept()
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

  const status: CardStatus = !isEnabled ? 'off' : config?.password_set ? 'on' : 'needs-setup'

  return (
    <SettingsCard
      title="Knowledge graph"
      subtitle="Remembers people, places and topics as a graph. Needs a Neo4j database."
      meta={config?.password_set ? 'Password saved' : 'No password saved'}
      icon={<Share2 size={14} />}
      status={status}
      unsaved={dirty}
      enabled={isEnabled}
      onToggle={handleToggle}
      toggleLabel="Knowledge graph"
      toggleDisabled={toggleState.status === 'busy'}
      open={isOpen}
      onOpenChange={setIsOpen}
    >
      <ErrorStatus state={toggleState} />

      <InfoNote>
        Connect to Neo4j Aura (free cloud) or a local Neo4j. Get a free instance at{' '}
        <a
          href="https://neo4j.com/cloud/aura-free/"
          target="_blank"
          rel="noopener noreferrer"
          className="text-dark-accent-text hover:underline"
        >
          neo4j.com/cloud/aura-free
        </a>
        . These settings are used by the Knowledge Graph page; chat uses the server's NEO4J settings in its .env file.
      </InfoNote>

      <TextField label="Connection URI" value={uri} onChange={setUri} placeholder="neo4j+s://xxxxx.databases.neo4j.io"
                 hint={savedUri ? 'Leave empty to keep the saved URI.' : undefined} />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <TextField label="Username" value={username} onChange={setUsername} placeholder="neo4j"
                   hint={config?.username ? 'Leave empty to keep the saved username.' : undefined} />
        <TextField label="Database" value={database} onChange={setDatabase} placeholder="neo4j" />
      </div>

      <PasswordField
        label="Password"
        value={password}
        onChange={setPassword}
        placeholder={config?.password_set ? 'Type a new password to replace it' : 'Enter password'}
        hint={config?.password_set ? 'Password saved. Leave empty to keep it.' : undefined}
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
