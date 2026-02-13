/**
 * Generic addin settings renderer.
 *
 * Section types:
 * - general: Collapsible card with field list (toggles, inputs, selects, etc.)
 * - llm_provider: Renders 3 individual provider cards (LM Studio, Ollama, OpenAI)
 *   using the EXACT same markup and styling as the main ProviderSettings component.
 *   Each card is self-contained: toggle, test, model refresh, save.
 *
 * NOT hardcoded per addin — any addin that declares a get_settings_schema()
 * will have its settings rendered here automatically.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Loader2, ChevronDown, ChevronRight, Check, X,
  Zap, RefreshCw,
} from 'lucide-react'
import { addinsApi } from '../../services/api'

/** A single field in a settings section. */
interface SettingsField {
  key: string
  label: string
  type: 'toggle' | 'text' | 'password' | 'select' | 'number' | 'range'
  placeholder?: string
  default?: unknown
  value?: unknown
  options?: { value: unknown; label: string }[]
  min?: number
  max?: number
  step?: number
  show_when?: Record<string, unknown[]>
}

/** A section in the settings schema. */
interface SettingsSection {
  id: string
  title: string
  description?: string
  type: 'general' | 'llm_provider'
  fields: SettingsField[]
}

/** Full schema returned by the backend. */
interface SettingsSchema {
  addin_id: string
  addin_name: string
  sections: SettingsSection[]
}

interface Props {
  addinName: string
}

async function fetchSchema(addinName: string): Promise<SettingsSchema | null> {
  try {
    const data = await addinsApi.getSettingsSchema(addinName)
    return (data && data.sections?.length > 0) ? data as SettingsSchema : null
  } catch {
    return null
  }
}

async function saveAddinSettings(addinName: string, settings: Record<string, unknown>) {
  return addinsApi.action(addinName, 'update_settings', settings)
}

export default function AddinSettingsRenderer({ addinName }: Props) {
  const [schema, setSchema] = useState<SettingsSchema | null>(null)
  const [loading, setLoading] = useState(true)
  const [values, setValues] = useState<Record<string, unknown>>({})

  const loadSchema = useCallback(async () => {
    setLoading(true)
    const result = await fetchSchema(addinName)
    if (result && result.sections.length > 0) {
      setSchema(result)
      const initial: Record<string, unknown> = {}
      for (const section of result.sections) {
        for (const field of section.fields) {
          initial[field.key] = field.value ?? field.default ?? ''
        }
      }
      setValues(initial)
    }
    setLoading(false)
  }, [addinName])

  useEffect(() => { loadSchema() }, [loadSchema])

  const updateValue = (key: string, val: unknown) => {
    setValues(prev => ({ ...prev, [key]: val }))
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-2">
        <Loader2 size={12} className="animate-spin text-dark-text-secondary" />
        <span className="text-[10px] text-dark-text-secondary">Loading settings...</span>
      </div>
    )
  }

  if (!schema || schema.sections.length === 0) return null

  const isFieldVisible = (field: SettingsField): boolean => {
    if (!field.show_when) return true
    for (const [depKey, allowedValues] of Object.entries(field.show_when)) {
      const currentVal = values[depKey]
      if (!allowedValues.includes(currentVal)) return false
    }
    return true
  }

  return (
    <div className="mt-3 space-y-3">
      {schema.sections.map(section =>
        section.type === 'llm_provider' ? (
          <AddinProviderCards
            key={section.id}
            addinName={addinName}
            currentProvider={String(values.llm_provider || 'lmstudio')}
            currentBaseUrl={String(values.llm_base_url || '')}
            currentApiKey={String(values.llm_api_key || '')}
            currentModel={String(values.llm_model || '')}
            onUpdate={updateValue}
          />
        ) : (
          <GeneralSectionCard
            key={section.id}
            section={section}
            values={values}
            addinName={addinName}
            onUpdate={updateValue}
            isFieldVisible={isFieldVisible}
          />
        )
      )}
    </div>
  )
}


/* ═══════════════════════════════════════════════════════════════════
 *  Provider metadata — same as main ProviderSettings.tsx
 * ═══════════════════════════════════════════════════════════════════ */
const ADDIN_PROVIDERS: Record<string, {
  name: string
  description: string
  defaultUrl: string
  needsApiKey: boolean
}> = {
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
  openai: {
    name: 'OpenAI',
    description: 'GPT-4o-mini (recommended — cheap & fast)',
    defaultUrl: 'https://api.openai.com/v1',
    needsApiKey: true,
  },
}


/**
 * Renders 3 individual provider cards — EXACT same design as main ProviderSettings.
 * Only one provider can be active at a time for the addin.
 */
function AddinProviderCards({ addinName, currentProvider, currentBaseUrl, currentApiKey, currentModel, onUpdate }: {
  addinName: string
  currentProvider: string
  currentBaseUrl: string
  currentApiKey: string
  currentModel: string
  onUpdate: (key: string, val: unknown) => void
}) {
  return (
    <div className="space-y-2">
      {Object.entries(ADDIN_PROVIDERS).map(([key, meta]) => (
        <AddinProviderCard
          key={key}
          providerKey={key}
          meta={meta}
          addinName={addinName}
          isActive={currentProvider === key}
          baseUrl={currentProvider === key ? currentBaseUrl : ''}
          apiKey={currentProvider === key ? currentApiKey : ''}
          model={currentProvider === key ? currentModel : ''}
          onUpdate={onUpdate}
        />
      ))}
    </div>
  )
}


/**
 * Single provider card — IDENTICAL markup to the main ProviderSettings component.
 * bg-dark-bg-secondary card, chevron, name, description, Active badge,
 * model count, enable toggle, expanded: URL/key/models/test/save.
 */
function AddinProviderCard({ providerKey, meta, addinName, isActive, baseUrl, apiKey, model, onUpdate }: {
  providerKey: string
  meta: { name: string; description: string; defaultUrl: string; needsApiKey: boolean }
  addinName: string
  isActive: boolean
  baseUrl: string
  apiKey: string
  model: string
  onUpdate: (key: string, val: unknown) => void
}) {
  const [isExpanded, setIsExpanded] = useState(isActive)
  const [localBaseUrl, setLocalBaseUrl] = useState(baseUrl)
  const [localApiKey, setLocalApiKey] = useState(apiKey)
  const [localModel, setLocalModel] = useState(model)
  const [isTesting, setIsTesting] = useState(false)
  const [testResult, setTestResult] = useState<boolean | null>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [models, setModels] = useState<string[]>([])
  const [isRefreshing, setIsRefreshing] = useState(false)

  // Sync when parent state changes
  useEffect(() => {
    if (isActive) {
      setLocalBaseUrl(baseUrl)
      setLocalApiKey(apiKey)
      setLocalModel(model)
    }
  }, [isActive, baseUrl, apiKey, model])

  const handleToggle = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (isActive) return // can't disable the active one without enabling another
    // Enable this provider, disable others
    onUpdate('llm_provider', providerKey)
    onUpdate('llm_base_url', localBaseUrl || '')
    onUpdate('llm_api_key', localApiKey || '')
    onUpdate('llm_model', localModel || '')
    setIsExpanded(true)
    // Auto-save the toggle
    try {
      await saveAddinSettings(addinName, {
        llm_provider: providerKey,
        llm_base_url: localBaseUrl || '',
        llm_api_key: localApiKey || '',
        llm_model: localModel || '',
      })
    } catch (err) {
      console.error('Failed to save provider toggle:', err)
    }
  }

  const handleTest = async () => {
    setIsTesting(true)
    setTestResult(null)
    try {
      const result = await addinsApi.action(addinName, 'test_llm', {
        provider: providerKey,
        base_url: localBaseUrl || meta.defaultUrl,
        api_key: localApiKey,
        model: localModel,
      })
      setTestResult(result?.success ?? false)
    } catch {
      setTestResult(false)
    } finally {
      setIsTesting(false)
    }
  }

  const handleSave = async () => {
    setIsSaving(true)
    try {
      onUpdate('llm_provider', providerKey)
      onUpdate('llm_base_url', localBaseUrl)
      onUpdate('llm_api_key', localApiKey)
      onUpdate('llm_model', localModel)
      await saveAddinSettings(addinName, {
        llm_provider: providerKey,
        llm_base_url: localBaseUrl,
        llm_api_key: localApiKey,
        llm_model: localModel,
      })
    } catch (err) {
      console.error('Failed to save:', err)
    } finally {
      setIsSaving(false)
    }
  }

  const handleRefreshModels = async () => {
    setIsRefreshing(true)
    try {
      const result = await addinsApi.action(addinName, 'list_models', {
        provider: providerKey,
        base_url: localBaseUrl || meta.defaultUrl,
        api_key: localApiKey,
      })
      setModels(result?.models || [])
    } catch {
      setModels([])
    } finally {
      setIsRefreshing(false)
    }
  }

  return (
    <div className={`rounded-lg border transition-colors ${
      isActive
        ? 'bg-dark-bg-secondary border-dark-accent-primary/30'
        : 'bg-dark-bg-secondary/50 border-dark-border/50'
    }`}>
      {/* Header row — EXACT same as main ProviderSettings */}
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer select-none"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        {isExpanded
          ? <ChevronDown size={14} className="text-dark-text-secondary flex-shrink-0" />
          : <ChevronRight size={14} className="text-dark-text-secondary flex-shrink-0" />
        }

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={`text-sm font-medium ${isActive ? 'text-dark-text-primary' : 'text-dark-text-secondary'}`}>
              {meta.name}
            </span>
            {isActive && (
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
            isActive ? 'bg-dark-accent-primary' : 'bg-dark-border'
          }`}
        >
          <span className={`inline-block w-4 h-4 rounded-full bg-white shadow-sm transition-transform ${
            isActive ? 'translate-x-5' : 'translate-x-1'
          }`} />
        </button>
      </div>

      {/* Expanded content — EXACT same as main ProviderSettings */}
      {isExpanded && (
        <div className="px-4 pb-4 pt-1 space-y-3 border-t border-dark-border/30">
          {/* API Key — only for cloud providers */}
          {meta.needsApiKey && (
            <div>
              <label className="text-xs font-medium text-dark-text-secondary block mb-1">API Key</label>
              <input
                type="password"
                value={localApiKey}
                onChange={e => setLocalApiKey(e.target.value)}
                placeholder="sk-..."
                className="w-full bg-dark-bg-primary border border-dark-border rounded-md
                           px-3 py-1.5 text-sm text-dark-text-primary placeholder:text-dark-text-secondary/40
                           focus:outline-none focus:border-dark-accent-primary/50 transition-colors"
              />
            </div>
          )}

          {/* Server URL — for local providers */}
          <div>
            <label className="text-xs font-medium text-dark-text-secondary block mb-1">
              {meta.needsApiKey ? 'Base URL' : 'Server URL'}
            </label>
            <input
              type="text"
              value={localBaseUrl}
              onChange={e => setLocalBaseUrl(e.target.value)}
              placeholder={meta.defaultUrl}
              className="w-full bg-dark-bg-primary border border-dark-border rounded-md
                         px-3 py-1.5 text-sm text-dark-text-primary placeholder:text-dark-text-secondary/40
                         focus:outline-none focus:border-dark-accent-primary/50 transition-colors"
            />
          </div>

          {/* Models — with refresh button */}
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
                    onClick={() => setLocalModel(m)}
                    className={`text-[11px] px-2 py-1 rounded transition-colors cursor-pointer ${
                      m === localModel
                        ? 'bg-dark-accent-primary/25 text-dark-accent-primary border border-dark-accent-primary/40 font-medium'
                        : 'bg-dark-bg-primary text-dark-text-secondary hover:bg-dark-accent-primary/20 hover:text-dark-text-primary'
                    }`}
                    title={m === localModel ? `${m} (selected)` : `Select ${m}`}
                  >
                    {m}
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

          {/* Action buttons — EXACT same as main ProviderSettings */}
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


/* ═══════════════════════════════════════════════════════════════════
 *  General section card — for non-provider settings (toggles, ranges, etc.)
 * ═══════════════════════════════════════════════════════════════════ */
function GeneralSectionCard({ section, values, addinName, onUpdate, isFieldVisible }: {
  section: SettingsSection
  values: Record<string, unknown>
  addinName: string
  onUpdate: (key: string, val: unknown) => void
  isFieldVisible: (field: SettingsField) => boolean
}) {
  const [isExpanded, setIsExpanded] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [saveResult, setSaveResult] = useState<boolean | null>(null)

  const handleSave = async () => {
    setIsSaving(true)
    setSaveResult(null)
    try {
      await saveAddinSettings(addinName, values)
      setSaveResult(true)
      setTimeout(() => setSaveResult(null), 2000)
    } catch {
      setSaveResult(false)
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="rounded-lg border border-dark-border/50 bg-dark-bg-secondary/50">
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer select-none"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        {isExpanded
          ? <ChevronDown size={14} className="text-dark-text-secondary flex-shrink-0" />
          : <ChevronRight size={14} className="text-dark-text-secondary flex-shrink-0" />
        }
        <div className="flex-1 min-w-0">
          <span className="text-sm font-medium text-dark-text-primary">{section.title}</span>
          {section.description && (
            <p className="text-xs text-dark-text-secondary truncate">{section.description}</p>
          )}
        </div>
      </div>

      {isExpanded && (
        <div className="px-4 pb-4 pt-1 space-y-3 border-t border-dark-border/30">
          {section.fields.filter(isFieldVisible).map(field => (
            <FieldRenderer
              key={field.key}
              field={field}
              value={values[field.key]}
              onChange={val => onUpdate(field.key, val)}
            />
          ))}

          <div className="flex items-center gap-2 pt-1">
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
            {saveResult !== null && (
              <span className={`flex items-center gap-1 text-xs ${saveResult ? 'text-green-400' : 'text-red-400'}`}>
                {saveResult ? <Check size={14} /> : <X size={14} />}
                {saveResult ? 'Saved' : 'Save failed'}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}


/** Renders a single field based on its type. */
function FieldRenderer({ field, value, onChange }: {
  field: SettingsField
  value: unknown
  onChange: (val: unknown) => void
}) {
  switch (field.type) {
    case 'toggle':
      return (
        <div className="flex items-center justify-between py-0.5">
          <span className="text-sm text-dark-text-primary">{field.label}</span>
          <button
            onClick={() => onChange(!value)}
            className={`relative inline-flex items-center w-10 h-6 rounded-full transition-colors ${
              value ? 'bg-dark-accent-primary' : 'bg-dark-border'
            }`}
          >
            <span className={`inline-block w-4 h-4 rounded-full bg-white shadow-sm transition-transform ${
              value ? 'translate-x-5' : 'translate-x-1'
            }`} />
          </button>
        </div>
      )

    case 'text':
      return (
        <div>
          <label className="text-xs font-medium text-dark-text-secondary block mb-1">{field.label}</label>
          <input
            type="text"
            value={(value as string) || ''}
            onChange={e => onChange(e.target.value)}
            placeholder={field.placeholder}
            className="w-full bg-dark-bg-primary border border-dark-border rounded-md
                       px-3 py-1.5 text-sm text-dark-text-primary placeholder:text-dark-text-secondary/40
                       focus:outline-none focus:border-dark-accent-primary/50 transition-colors"
          />
        </div>
      )

    case 'select':
      return (
        <div>
          <label className="text-xs font-medium text-dark-text-secondary block mb-1">{field.label}</label>
          <select
            value={String(value ?? field.default ?? '')}
            onChange={e => {
              const opt = field.options?.find(o => String(o.value) === e.target.value)
              onChange(opt ? opt.value : e.target.value)
            }}
            className="w-full bg-dark-bg-primary border border-dark-border rounded-md px-3 py-1.5
                       text-sm text-dark-text-primary appearance-none cursor-pointer
                       focus:outline-none focus:border-dark-accent-primary/50 transition-colors"
          >
            {(field.options || []).map(opt => (
              <option key={String(opt.value)} value={String(opt.value)}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      )

    case 'number':
      return (
        <div>
          <label className="text-xs font-medium text-dark-text-secondary block mb-1">{field.label}</label>
          <input
            type="number"
            value={String(Number(value) || Number(field.default) || 0)}
            onChange={e => onChange(Number(e.target.value))}
            min={field.min}
            max={field.max}
            className="w-full bg-dark-bg-primary border border-dark-border rounded-md px-3 py-1.5
                       text-sm text-dark-text-primary
                       focus:outline-none focus:border-dark-accent-primary/50 transition-colors"
          />
        </div>
      )

    case 'range':
      return (
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs font-medium text-dark-text-secondary">{field.label}</label>
            <span className="text-xs text-dark-text-primary font-mono">
              {Number(value ?? field.default ?? 0).toFixed(2)}
            </span>
          </div>
          <input
            type="range"
            value={String(Number(value ?? field.default ?? 0))}
            onChange={e => onChange(Number(e.target.value))}
            min={field.min}
            max={field.max}
            step={field.step}
            className="w-full h-1.5 bg-dark-bg-primary rounded-full appearance-none cursor-pointer
                       accent-dark-accent-primary"
          />
        </div>
      )

    default:
      return null
  }
}
