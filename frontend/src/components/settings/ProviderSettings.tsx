/**
 * Individual provider settings card.
 * Renders a collapsible card with enable toggle, config fields, and actions.
 *
 * @param provider - Provider key (e.g. 'openai', 'anthropic')
 * @param config - Current provider configuration from the backend
 * @param onUpdate - Callback to refresh parent settings after save
 */

import { useState, useEffect } from 'react'
import {
  Check, X, RefreshCw, ChevronDown, ChevronRight,
  Zap, Loader2, Terminal
} from 'lucide-react'
import { settingsApi } from '../../services/api'
import { friendlyModelName } from '../../utils/modelNames'
import type { ProviderConfig } from '../../types/chat.types'

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
  setupHint?: string
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
  const [isTesting, setIsTesting] = useState(false)
  const [testResult, setTestResult] = useState<boolean | null>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [models, setModels] = useState<string[]>(config?.available_models || [])
  const [isExpanded, setIsExpanded] = useState(config?.enabled || false)

  // Sync local state when parent refreshes config from backend
  useEffect(() => {
    setIsEnabled(config?.enabled || false)
    setModels(config?.available_models || [])
    setBaseUrl(config?.base_url || '')
  }, [config?.enabled, config?.available_models, config?.base_url])

  const meta = PROVIDER_META[provider] || {
    name: provider, description: '', defaultUrl: '', needsApiKey: false
  }

  const handleSave = async () => {
    setIsSaving(true)
    try {
      await settingsApi.updateLLMSettings({
        providers: {
          [provider]: {
            enabled: isEnabled,
            api_key: apiKey || undefined,
            base_url: baseUrl || undefined,
          }
        }
      })
      onUpdate()
    } catch (error) {
      console.error('Failed to save settings:', error)
    } finally {
      setIsSaving(false)
    }
  }

  const handleTest = async () => {
    setIsTesting(true)
    setTestResult(null)
    try {
      const result = await settingsApi.testConnection(provider, apiKey, baseUrl)
      setTestResult(result.success)
    } catch {
      setTestResult(false)
    } finally {
      setIsTesting(false)
    }
  }

  const handleRefreshModels = async () => {
    setIsRefreshing(true)
    try {
      const data = await settingsApi.getModels(provider)
      setModels(data.map((m: { id: string }) => m.id))
    } catch (error) {
      console.error('Failed to fetch models:', error)
    } finally {
      setIsRefreshing(false)
    }
  }

  // Toggle enable/disable and auto-save immediately
  const handleToggle = async (e: React.MouseEvent) => {
    e.stopPropagation()
    const next = !isEnabled
    setIsEnabled(next)
    if (next) setIsExpanded(true)
    // Auto-save the toggle so users don't have to click Save
    try {
      await settingsApi.updateLLMSettings({
        providers: {
          [provider]: {
            enabled: next,
            api_key: apiKey || undefined,
            base_url: baseUrl || undefined,
          }
        }
      })
      onUpdate()
    } catch (error) {
      console.error('Failed to toggle provider:', error)
      setIsEnabled(!next) // revert on failure
    }
  }

  return (
    <div className={`rounded-lg border transition-colors ${
      isEnabled
        ? 'bg-dark-bg-secondary border-dark-accent-primary/30'
        : 'bg-dark-bg-secondary/50 border-dark-border/50'
    }`}>
      {/* Header row — always visible */}
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer select-none"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        {/* Expand chevron */}
        {isExpanded
          ? <ChevronDown size={14} className="text-dark-text-secondary flex-shrink-0" />
          : <ChevronRight size={14} className="text-dark-text-secondary flex-shrink-0" />
        }

        {/* Name + description */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={`text-sm font-medium ${isEnabled ? 'text-dark-text-primary' : 'text-dark-text-secondary'}`}>
              {meta.name}
            </span>
            {isEnabled && (
              <span className="flex items-center gap-1 text-[10px] font-medium text-green-400 bg-green-400/10 px-1.5 py-0.5 rounded-full">
                <Zap size={8} /> Active
              </span>
            )}
          </div>
          <p className="text-xs text-dark-text-secondary truncate">{meta.description}</p>
        </div>

        {/* Models count badge */}
        {models.length > 0 && (
          <span className="text-[10px] text-dark-text-secondary bg-dark-bg-primary px-2 py-0.5 rounded-full flex-shrink-0">
            {models.length} model{models.length !== 1 ? 's' : ''}
          </span>
        )}

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
          {/* CLI setup hint */}
          {meta.setupHint && (
            <div className="flex items-start gap-2 bg-dark-bg-primary/60 rounded-md px-3 py-2">
              <Terminal size={12} className="text-dark-accent-primary mt-0.5 flex-shrink-0" />
              <div className="text-xs text-dark-text-secondary">
                <span className="text-dark-text-primary font-medium">Setup: </span>
                <code className="text-dark-accent-primary">{meta.setupHint}</code>
              </div>
            </div>
          )}

          {/* API Key */}
          {meta.needsApiKey && (
            <div>
              <label className="text-xs font-medium text-dark-text-secondary block mb-1">API Key</label>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={config?.api_key_set ? '••••••••••••' : 'sk-...'}
                className="w-full bg-dark-bg-primary border border-dark-border rounded-md
                           px-3 py-1.5 text-sm text-dark-text-primary placeholder:text-dark-text-secondary/40
                           focus:outline-none focus:border-dark-accent-primary/50 transition-colors"
              />
              {config?.api_key_masked && (
                <p className="text-[10px] text-dark-text-secondary mt-1">
                  Current: {config.api_key_masked}
                </p>
              )}
            </div>
          )}

          {/* Base URL — show for local providers and cloud providers, hide for CLI providers */}
          {meta.defaultUrl && (
            <div>
              <label className="text-xs font-medium text-dark-text-secondary block mb-1">
                {meta.needsApiKey ? 'Base URL' : 'Server URL'}
              </label>
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder={meta.defaultUrl}
                className="w-full bg-dark-bg-primary border border-dark-border rounded-md
                           px-3 py-1.5 text-sm text-dark-text-primary placeholder:text-dark-text-secondary/40
                           focus:outline-none focus:border-dark-accent-primary/50 transition-colors"
              />
            </div>
          )}

          {/* Models */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs font-medium text-dark-text-secondary">Models</label>
              <button
                onClick={handleRefreshModels}
                disabled={isRefreshing}
                className="text-dark-accent-primary hover:text-dark-accent-hover transition-colors disabled:opacity-50"
                title="Refresh models"
              >
                <RefreshCw size={12} className={isRefreshing ? 'animate-spin' : ''} />
              </button>
            </div>
            {models.length > 0 ? (
              <div className="flex flex-wrap gap-1">
                {models.slice(0, 12).map(m => (
                  <button
                    key={m}
                    onClick={async () => {
                      try {
                        await settingsApi.updateLLMSettings({
                          default_provider: provider,
                          default_model: m,
                        })
                        onUpdate()
                      } catch (error) {
                        console.error('Failed to set default model:', error)
                      }
                    }}
                    className={`text-[11px] px-2 py-1 rounded transition-colors cursor-pointer ${
                      m === defaultModel
                        ? 'bg-dark-accent-primary/25 text-dark-accent-primary border border-dark-accent-primary/40 font-medium'
                        : 'bg-dark-bg-primary text-dark-text-secondary hover:bg-dark-accent-primary/20 hover:text-dark-text-primary active:bg-dark-accent-primary/30'
                    }`}
                    title={m === defaultModel ? `${m} (default)` : `Set ${friendlyModelName(m)} as default`}
                  >
                    {friendlyModelName(m)}
                  </button>
                ))}
                {models.length > 12 && (
                  <span className="text-[11px] text-dark-text-secondary px-1 py-0.5">
                    +{models.length - 12} more
                  </span>
                )}
              </div>
            ) : (
              <p className="text-xs text-dark-text-secondary/50 italic">
                No models detected — click refresh
              </p>
            )}
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2 pt-1">
            <button
              onClick={handleTest}
              disabled={isTesting}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-dark-bg-primary border border-dark-border
                         rounded-md text-xs text-dark-text-primary hover:bg-dark-border/80
                         disabled:opacity-50 transition-colors"
            >
              {isTesting
                ? <><Loader2 size={12} className="animate-spin" /> Testing...</>
                : 'Test'
              }
            </button>
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-dark-accent-primary hover:bg-dark-accent-hover
                         rounded-md text-xs text-white disabled:opacity-50 transition-colors"
            >
              {isSaving
                ? <><Loader2 size={12} className="animate-spin" /> Saving...</>
                : 'Save'
              }
            </button>

            {/* Test result indicator */}
            {testResult !== null && (
              <span className={`flex items-center gap-1 text-xs ${testResult ? 'text-green-400' : 'text-red-400'}`}>
                {testResult ? <Check size={14} /> : <X size={14} />}
                {testResult ? 'Connected' : 'Failed'}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
