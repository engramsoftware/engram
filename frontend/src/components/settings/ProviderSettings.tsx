/**
 * Individual provider settings card.
 * Enable switch (one provider is active at a time; the backend disables the
 * others), API key / base URL, the model list and default-model choice.
 *
 * @param provider - Provider key (e.g. 'openai', 'anthropic')
 * @param config - Current provider configuration from the backend
 * @param defaultModel - The user's default model, highlighted in the list
 * @param onUpdate - Callback to refresh parent settings after save
 */

import { useState, useEffect } from 'react'
import { RefreshCw, Zap } from 'lucide-react'
import { settingsApi } from '../../services/api'
import { friendlyModelName } from '../../utils/modelNames'
import type { ProviderConfig } from '../../types/chat.types'
import { ActionButton, ActionStatus, Badge, SettingsCard, TextField, useAction } from './primitives'

interface Props {
  provider: string
  config: ProviderConfig
  defaultModel?: string
  onUpdate: () => void
}

/** Provider metadata: display name, description, default URL, whether it needs an API key */
const PROVIDER_META: Record<string, {
  name: string
  description: string
  defaultUrl: string
  needsApiKey: boolean
}> = {
  openai: {
    name: 'OpenAI',
    description: 'GPT-4o, GPT-4, GPT-3.5 Turbo',
    defaultUrl: 'https://api.openai.com/v1',
    needsApiKey: true,
  },
  anthropic: {
    name: 'Anthropic',
    description: 'Claude Sonnet 4, Opus 4, Haiku',
    defaultUrl: 'https://api.anthropic.com',
    needsApiKey: true,
  },
  lmstudio: {
    name: 'LM Studio',
    description: 'Local models via LM Studio server',
    defaultUrl: 'http://host.docker.internal:1234/v1',
    needsApiKey: false,
  },
  ollama: {
    name: 'Ollama',
    description: 'Local models via Ollama',
    defaultUrl: 'http://host.docker.internal:11434',
    needsApiKey: false,
  },
}

export default function ProviderSettings({ provider, config, defaultModel, onUpdate }: Props) {
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(config?.base_url || '')
  const [isEnabled, setIsEnabled] = useState(config?.enabled || false)
  const [models, setModels] = useState<string[]>(config?.available_models || [])
  const [isOpen, setIsOpen] = useState(config?.enabled || false)
  const [saveState, runSave] = useAction()
  const [testState, runTest] = useAction()
  const [toggleState, runToggle] = useAction()
  const [modelState, runModel] = useAction()

  // Sync from the backend after a refresh, one value per effect. A single effect
  // keyed on the models array re-ran on every refresh (a new array each time) and
  // wiped a base URL the user was still typing.
  useEffect(() => { setIsEnabled(config?.enabled || false) }, [config?.enabled])
  useEffect(() => { setBaseUrl(config?.base_url || '') }, [config?.base_url])
  const modelsKey = (config?.available_models || []).join('\n')
  useEffect(() => { setModels(modelsKey ? modelsKey.split('\n') : []) }, [modelsKey])

  const meta = PROVIDER_META[provider] || {
    name: provider, description: '', defaultUrl: '', needsApiKey: false
  }

  const save = (enabled: boolean) => settingsApi.updateLLMSettings({
    providers: {
      [provider]: {
        enabled,
        api_key: apiKey || undefined,
        base_url: baseUrl || undefined,
      }
    }
  })

  const handleSave = () => runSave(async () => {
    await save(isEnabled)
    setApiKey('')
    onUpdate()
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
    }, next ? `${meta.name} enabled` : `${meta.name} disabled`)
  }

  const handleTest = () => runTest(async () => {
    const result = await settingsApi.testConnection(provider, apiKey, baseUrl)
    if (!result.success) throw new Error(result.error || result.message || 'no response from the provider')
  }, 'Connected', 'Connection failed')

  const handleRefreshModels = () => runModel(async () => {
    const data = await settingsApi.getModels(provider)
    setModels(data.map((m: { id: string }) => m.id))
  }, 'Model list refreshed', "Couldn't load models")

  const handleDefaultModel = (model: string) => runModel(async () => {
    await settingsApi.updateLLMSettings({ default_provider: provider, default_model: model })
    onUpdate()
  }, `Default model: ${friendlyModelName(model)}`)

  return (
    <SettingsCard
      title={meta.name}
      subtitle={meta.description}
      enabled={isEnabled}
      onToggle={handleToggle}
      toggleDisabled={toggleState.status === 'busy'}
      open={isOpen}
      onOpenChange={setIsOpen}
      badges={isEnabled ? <Badge tone="green"><Zap size={8} /> Active</Badge> : undefined}
      aside={models.length > 0 ? <Badge>{models.length} model{models.length !== 1 ? 's' : ''}</Badge> : undefined}
    >
      <ActionStatus state={toggleState.status === 'error' ? toggleState : { status: 'idle' }} />

      {meta.needsApiKey && (
        <TextField
          label="API key"
          type="password"
          value={apiKey}
          onChange={setApiKey}
          placeholder={config?.api_key_set ? 'Saved; leave empty to keep it' : 'sk-...'}
          hint={config?.api_key_masked ? `Current: ${config.api_key_masked}` : undefined}
        />
      )}

      {meta.defaultUrl && (
        <TextField
          label={meta.needsApiKey ? 'Base URL' : 'Server URL'}
          type="url"
          value={baseUrl}
          onChange={setBaseUrl}
          placeholder={meta.defaultUrl}
        />
      )}

      {/* Models: pick the default */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs font-medium text-dark-text-secondary">Default model</span>
          <button
            type="button"
            onClick={handleRefreshModels}
            disabled={modelState.status === 'busy'}
            aria-label="Refresh models"
            title="Refresh models"
            className="p-1 rounded text-dark-accent-primary hover:text-dark-accent-hover transition-colors disabled:opacity-50"
          >
            <RefreshCw size={12} className={modelState.status === 'busy' ? 'animate-spin' : ''} />
          </button>
        </div>
        {models.length > 0 ? (
          <div className="flex flex-wrap gap-1 max-h-40 overflow-y-auto" role="group" aria-label={`${meta.name} models`}>
            {models.map(m => {
              const isDefault = m === defaultModel
              return (
                <button
                  key={m}
                  type="button"
                  onClick={() => handleDefaultModel(m)}
                  disabled={!isEnabled || modelState.status === 'busy'}
                  aria-pressed={isDefault}
                  title={!isEnabled
                    ? 'Enable this provider to choose its default model'
                    : isDefault ? `${m} (default)` : `Use ${friendlyModelName(m)} by default`}
                  className={`text-[11px] px-2 py-1 rounded border transition-colors
                              disabled:cursor-not-allowed disabled:opacity-60 ${
                    isDefault
                      ? 'bg-dark-accent-primary/15 border-dark-accent-primary text-dark-text-primary font-medium'
                      : 'bg-dark-bg-primary border-transparent text-dark-text-secondary hover:border-dark-border hover:text-dark-text-primary'
                  }`}
                >
                  {friendlyModelName(m)}
                </button>
              )
            })}
          </div>
        ) : (
          <p className="text-xs text-dark-text-secondary italic">No models detected. Use refresh after saving.</p>
        )}
        <ActionStatus state={modelState} />
      </div>

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
