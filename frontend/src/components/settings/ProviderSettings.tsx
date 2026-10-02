/**
 * One provider in the Models radio list.
 *
 * Choosing the radio makes this the provider new chats use (it saves at once).
 * A cloud provider without a saved key can't be chosen until a key is saved,
 * so "In use" never points at a provider that can't answer. The expanded row
 * holds the key / server URL (drafts until Save), the model list, Test and Save.
 *
 * Request shapes follow backend/routers/settings.py (see activateProvider).
 */

import { useState, useEffect, useId, useRef } from 'react'
import { RefreshCw } from 'lucide-react'
import { settingsApi } from '../../services/api'
import { friendlyModelName } from '../../utils/modelNames'
import { providerMeta } from '../../utils/providers'
import type { LLMSettings, ProviderConfig } from '../../types/chat.types'
import {
  ActionButton, ActionRow, ActionStatus, Disclosure, ErrorStatus, InfoNote, PasswordField, StatusPill,
  TextField, UnsavedPill, useAction, useDirty, type CardStatus,
} from './primitives'

/**
 * Make `provider` the one new chats use, optionally with a specific model.
 *
 * The backend replaces a provider's base URL with whatever is sent, so the
 * current URL always goes along. Enabling a provider that was off also resets
 * the default model to its first cached model and ignores a model sent in the
 * same request, so the default is set in a second request when it differs.
 */
export async function activateProvider(
  provider: string,
  before: LLMSettings,
  opts: { apiKey?: string; baseUrl?: string; model?: string } = {},
) {
  const after: LLMSettings = await settingsApi.updateLLMSettings({
    providers: { [provider]: { enabled: true, api_key: opts.apiKey || undefined, base_url: opts.baseUrl || undefined } },
  })
  const keepCurrent = before.default_provider === provider ? before.default_model : undefined
  const model = opts.model ?? keepCurrent ?? after.providers[provider]?.available_models?.[0] ?? ''
  if (after.default_provider !== provider || (after.default_model ?? '') !== model) {
    await settingsApi.updateLLMSettings({ default_provider: provider, default_model: model })
  }
}

interface Props {
  provider: string
  config: ProviderConfig
  settings: LLMSettings
  /** This provider is the one new chats use */
  inUse: boolean
  /** Chosen while it still needs a key: the radio waits for Save */
  pending: boolean
  onPendingChange: (pending: boolean) => void
  onUpdate: () => void
}

export default function ProviderSettings({ provider, config, settings, inUse, pending, onPendingChange, onUpdate }: Props) {
  const meta = providerMeta(provider)
  const savedUrl = config?.base_url || ''
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(savedUrl)
  const [models, setModels] = useState<string[]>(config?.available_models || [])
  const [isOpen, setIsOpen] = useState(inUse)
  const [saveState, runSave] = useAction()
  const [testState, runTest, resetTest] = useAction({ sticky: true })
  // A test result describes the values it was run with; editing them clears it
  useEffect(() => { resetTest() }, [apiKey, baseUrl, resetTest])
  const [selectState, runSelect] = useAction()
  const [modelState, runModel] = useAction()
  const keyRef = useRef<HTMLInputElement>(null)
  const statusId = useId()

  // Sync from the backend after a refresh, one value per effect, so a refresh
  // doesn't wipe a URL that is still being typed
  useEffect(() => { setBaseUrl(savedUrl) }, [savedUrl])
  const modelsKey = (config?.available_models || []).join('\n')
  useEffect(() => { setModels(modelsKey ? modelsKey.split('\n') : []) }, [modelsKey])

  const dirty = apiKey !== '' || baseUrl !== savedUrl
  useDirty(dirty)

  const hasKey = !meta.needsApiKey || !!config?.api_key_set
  const defaultModel = settings.default_provider === provider ? settings.default_model : undefined

  // Radio: switch now, or (no key yet) open the row and ask for one first
  const select = () => {
    if (inUse) return
    if (!hasKey && !apiKey) {
      onPendingChange(true)
      setIsOpen(true)
      setTimeout(() => keyRef.current?.focus(), 0)
      return
    }
    runSelect(async () => {
      await activateProvider(provider, settings, { apiKey, baseUrl })
      setApiKey('')
      onPendingChange(false)
      onUpdate()
    }, `Now using ${meta.name}`, `Couldn't switch to ${meta.name}`)
  }

  // Save: a pending or in-use provider is (re)activated with the typed values;
  // any other provider stays off, as only one provider is on at a time
  const handleSave = () => runSave(async () => {
    if (inUse || pending) {
      await activateProvider(provider, settings, { apiKey, baseUrl })
      onPendingChange(false)
    } else {
      await settingsApi.updateLLMSettings({
        providers: { [provider]: { enabled: false, api_key: apiKey || undefined, base_url: baseUrl || undefined } },
      })
    }
    setApiKey('')
    onUpdate()
  }, pending ? `Saved. Now using ${meta.name}` : 'Saved')

  const handleTest = () => runTest(async () => {
    const result = await settingsApi.testConnection(provider, apiKey, baseUrl)
    if (!result.success) throw new Error(result.error || result.message || 'no response from the provider')
  }, 'Connected', 'Connection failed')

  const handleRefreshModels = () => runModel(async () => {
    const data = await settingsApi.getModels(provider)
    setModels(data.map((m: { id: string }) => m.id))
  }, 'Model list refreshed', "Couldn't load models")

  // In use: the model becomes the default. Otherwise switch to this provider with that model.
  const pickModel = (model: string) => runModel(async () => {
    if (inUse) {
      await settingsApi.updateLLMSettings({ default_provider: provider, default_model: model })
    } else {
      await activateProvider(provider, settings, { apiKey, baseUrl, model })
      setApiKey('')
      onPendingChange(false)
    }
    onUpdate()
  }, inUse ? `New chats use ${friendlyModelName(model)}` : `Now using ${meta.name} · ${friendlyModelName(model)}`)

  const status: CardStatus = inUse ? (hasKey ? 'in-use' : 'needs-setup') : pending ? 'needs-setup' : 'off'
  const keyStatus = !meta.needsApiKey
    ? 'On this computer'
    : config?.api_key_set ? `Key saved · ${config.api_key_masked ?? ''}` : 'Needs an API key'
  const saveBlocked = pending && !apiKey && !hasKey

  return (
    <div className={`rounded-lg border transition-colors ${
      inUse ? 'bg-dark-bg-secondary border-dark-accent-primary/40' : 'bg-dark-bg-secondary/50 border-dark-border/60'
    }`}>
      <div className="flex items-center gap-3 px-4 py-3">
        <label className="flex-1 min-w-0 flex items-center gap-3 cursor-pointer">
          <input
            type="radio"
            name="llm-provider"
            value={provider}
            checked={inUse}
            onChange={select}
            aria-label={meta.name}
            aria-describedby={statusId}
            disabled={selectState.status === 'busy'}
            className="w-4 h-4 flex-shrink-0 accent-dark-accent-primary cursor-pointer"
          />
          <span className="min-w-0">
            <span className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-medium text-dark-text-primary">{meta.name}</span>
              <span id={statusId} className="contents">
                <StatusPill status={status} />
                {dirty && <UnsavedPill />}
                <span className="sr-only">. {keyStatus}</span>
              </span>
            </span>
            <span aria-hidden className="block text-[11px] text-dark-text-secondary truncate">{keyStatus}</span>
          </span>
        </label>
        <button
          type="button"
          onClick={() => setIsOpen(!isOpen)}
          aria-expanded={isOpen}
          aria-label={`${hasKey ? 'Edit' : 'Set up'} ${meta.name}`}
          className="flex-shrink-0 px-2 py-1.5 min-h-[40px] sm:min-h-0 rounded text-xs text-dark-accent-text hover:underline
                     focus:outline-none focus-visible:ring-2 focus-visible:ring-dark-accent-primary"
        >
          {hasKey ? 'Edit' : 'Set up'} {isOpen ? '▾' : '›'}
        </button>
      </div>
      <div className="px-4"><ErrorStatus state={selectState} /></div>

      {isOpen && (
        <div className="px-4 pb-4 pt-3 space-y-3 border-t border-dark-border/40">
          {pending && (
            <InfoNote>Add your {meta.name} API key, then Save to start using {meta.name}.</InfoNote>
          )}

          {meta.needsApiKey && (
            <PasswordField
              ref={keyRef}
              label="API key"
              value={apiKey}
              onChange={setApiKey}
              placeholder={config?.api_key_set ? 'Paste a new key to replace it' : meta.keyPlaceholder}
              hint={config?.api_key_set
                ? `Key saved · ${config.api_key_masked ?? ''}. Leave empty to keep it.`
                : meta.keyUrl ? <>Get a key at <a href={meta.keyUrl} target="_blank" rel="noopener noreferrer"
                    className="text-dark-accent-text hover:underline">{new URL(meta.keyUrl).host}</a></> : undefined}
            />
          )}

          {meta.needsApiKey ? (
            <Disclosure summary="Advanced: base URL" defaultOpen={!!savedUrl}>
              <TextField label="Base URL" type="url" value={baseUrl} onChange={setBaseUrl} placeholder={meta.defaultUrl}
                         hint="Only change this for a proxy or a compatible service." />
            </Disclosure>
          ) : (
            <TextField label="Server URL" type="url" value={baseUrl} onChange={setBaseUrl} placeholder={meta.defaultUrl}
                       hint={`Leave empty for the default (${meta.defaultUrl}).`} />
          )}

          {/* Models */}
          <div>
            <div className="flex items-center justify-between gap-2 mb-1">
              <span className="text-xs font-medium text-dark-text-secondary">
                {models.length > 0 ? `${models.length} model${models.length !== 1 ? 's' : ''}` : 'Models'}
              </span>
              <button
                type="button"
                onClick={handleRefreshModels}
                disabled={modelState.status === 'busy'}
                className="inline-flex items-center gap-1 px-2 py-1 min-h-[36px] sm:min-h-0 rounded text-xs text-dark-accent-text
                           hover:underline disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-dark-accent-primary"
              >
                <RefreshCw size={12} className={modelState.status === 'busy' ? 'animate-spin' : ''} /> Refresh
              </button>
            </div>
            {models.length > 0 ? (
              <>
                {!inUse && (
                  <p className="text-[11px] text-dark-text-secondary mb-1">
                    {hasKey ? `Pick a model to switch to ${meta.name} with it.` : `Save a key first to use ${meta.name}.`}
                  </p>
                )}
                <div className="flex flex-wrap gap-1 max-h-40 overflow-y-auto" role="group" aria-label={`${meta.name} models`}>
                  {models.map(m => {
                    const isDefault = m === defaultModel
                    return (
                      <button
                        key={m}
                        type="button"
                        onClick={() => pickModel(m)}
                        disabled={modelState.status === 'busy' || (!inUse && !hasKey && !apiKey)}
                        aria-pressed={isDefault}
                        title={m}
                        className={`text-[11px] px-2 py-1.5 sm:py-1 rounded border transition-colors
                                    disabled:cursor-not-allowed disabled:opacity-60 ${
                          isDefault
                            ? 'bg-dark-accent-primary/15 border-dark-accent-primary text-dark-text-primary font-medium'
                            : 'bg-dark-bg-primary border-transparent text-dark-text-secondary hover:border-dark-border hover:text-dark-text-primary'
                        }`}
                      >
                        {friendlyModelName(m)}{isDefault && ' · default'}
                      </button>
                    )
                  })}
                </div>
              </>
            ) : (
              <p className="text-xs text-dark-text-secondary italic">
                {meta.needsApiKey ? 'No models yet. Save your key, then press Refresh.' : 'No models yet. Start the app, then press Refresh.'}
              </p>
            )}
            <ActionStatus state={modelState} />
          </div>

          <ActionRow>
            <ActionButton onClick={handleTest} busy={testState.status === 'busy'}>
              {testState.status === 'busy' ? 'Testing…' : 'Test'}
            </ActionButton>
            <ActionButton variant="primary" onClick={handleSave} busy={saveState.status === 'busy'}
                          disabled={saveBlocked || (!dirty && !pending)}>
              {saveState.status === 'busy' ? 'Saving…' : pending ? `Save and use ${meta.name}` : 'Save'}
            </ActionButton>
            <ActionStatus state={testState} />
            <ActionStatus state={saveState} />
          </ActionRow>
        </div>
      )}
    </div>
  )
}
