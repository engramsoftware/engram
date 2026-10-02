/**
 * Generic add-in settings renderer.
 *
 * Any add-in that declares get_settings_schema() gets its settings rendered
 * here. Section types:
 * - general: switches, selects and sliders save as soon as they change (only
 *   that key is sent); text and number fields are drafts saved by the
 *   section's Save, which sends only that section's typed fields.
 * - llm_provider: one provider select (saves at once) followed by that
 *   provider's fields, Test and Save. Only these four llm_* keys are sent.
 *
 * Skill Voyager notes (backend facts, shown to the user rather than hidden):
 * its settings apply to everyone and live in memory until the server
 * restarts; only the server URL is used today (for finding a local model).
 */

import { useState, useEffect, useCallback } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'
import { addinsApi } from '../../services/api'
import {
  ActionButton, ActionRow, ActionStatus, ErrorStatus, InfoNote, PasswordField, SelectField, Switch,
  TextField, UnsavedPill, useAction, useDirty,
} from './primitives'

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
  /** Secret fields: a value is saved on the server (it is never sent back). */
  is_set?: boolean
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
  /** Settings shared by everyone: only admins can change them */
  read_only?: boolean
}

type Values = Record<string, unknown>

interface Props {
  addinName: string
  /** The add-in is turned off: show whether it has settings, not the fields. */
  disabled?: boolean
}

const saveSettings = (addinName: string, settings: Values) => addinsApi.action(addinName, 'update_settings', settings)

/** Field types that save as soon as they change. */
const INSTANT = new Set(['toggle', 'select', 'range'])

const initialValues = (schema: SettingsSchema): Values => {
  const values: Values = {}
  for (const section of schema.sections) {
    for (const field of section.fields) values[field.key] = field.value ?? field.default ?? ''
  }
  return values
}

export default function AddinSettingsRenderer({ addinName, disabled = false }: Props) {
  const [schema, setSchema] = useState<SettingsSchema | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  // What the server has (after the last load or successful save)
  const [saved, setSaved] = useState<Values>({})

  const loadSchema = useCallback(async () => {
    setLoading(true)
    try {
      const data = await addinsApi.getSettingsSchema(addinName)
      const result = data && data.sections?.length > 0 ? data as SettingsSchema : null
      setSchema(result)
      setSaved(result ? initialValues(result) : {})
      setLoadFailed(false)
    } catch {
      setLoadFailed(true)
    } finally {
      setLoading(false)
    }
  }, [addinName])

  useEffect(() => { loadSchema() }, [loadSchema])

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-2">
        <Loader2 size={12} className="animate-spin text-dark-text-secondary" />
        <span className="text-xs text-dark-text-secondary">Loading settings…</span>
      </div>
    )
  }
  if (loadFailed) {
    return (
      <div role="alert" className="flex items-center gap-3 text-xs text-red-400 [.light_&]:text-red-700">
        Couldn't load this add-in's settings.
        <ActionButton onClick={loadSchema}>Retry</ActionButton>
      </div>
    )
  }
  if (!schema) return <p className="text-xs text-dark-text-secondary">This add-in has no settings.</p>
  if (schema.read_only) {
    return <p className="text-xs text-dark-text-secondary">These settings apply to everyone on this Engram, so only an admin can change them.</p>
  }

  const applySaved = (patch: Values) => setSaved(prev => ({ ...prev, ...patch }))

  // Turned off: the fields are hidden but stay mounted, so typed values aren't lost
  return (
    <>
    {disabled && <p className="text-xs text-dark-text-secondary">Turn this add-in on to change its settings.</p>}
    <div className="space-y-3" hidden={disabled}>
      {addinName === 'skill_voyager' && (
        <InfoNote>These settings apply to everyone on this Engram and reset when the server restarts.</InfoNote>
      )}
      {schema.sections.map(section =>
        section.type === 'llm_provider' ? (
          <ProviderSection key={section.id} addinName={addinName} section={section} saved={saved} onSaved={applySaved} />
        ) : (
          <GeneralSection key={section.id} addinName={addinName} section={section} saved={saved} onSaved={applySaved} />
        )
      )}
    </div>
    </>
  )
}

// ------------------------------------------------------------------ Provider section

const LOCAL_DEFAULT_URLS: Record<string, string> = {
  lmstudio: 'http://host.docker.internal:1234',
  ollama: 'http://host.docker.internal:11434',
}
const CLOUD = new Set(['openai', 'anthropic'])

function ProviderSection({ addinName, section, saved, onSaved }: {
  addinName: string; section: SettingsSection; saved: Values; onSaved: (patch: Values) => void
}) {
  const providerField = section.fields.find(f => f.key === 'llm_provider')
  const keyField = section.fields.find(f => f.key === 'llm_api_key')
  const options = (providerField?.options ?? []).map(o => ({ value: String(o.value), label: String(o.label) }))
  const savedProvider = String(saved.llm_provider || 'auto')
  const savedUrl = String(saved.llm_base_url || '')
  const savedModel = String(saved.llm_model || '')

  const [provider, setProvider] = useState(savedProvider)
  const [baseUrl, setBaseUrl] = useState(savedUrl)
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState(savedModel)
  const [models, setModels] = useState<string[]>([])
  const [keySaved, setKeySaved] = useState(!!keyField?.is_set)
  const [selectState, runSelect] = useAction()
  const [saveState, runSave] = useAction()
  const [testState, runTest, resetTest] = useAction({ sticky: true })
  const [listState, runList] = useAction()
  useEffect(() => { resetTest() }, [provider, baseUrl, apiKey, model, resetTest])

  const isLocal = provider === 'lmstudio' || provider === 'ollama'
  const isCloud = CLOUD.has(provider)
  const dirty = baseUrl !== savedUrl || apiKey !== '' || model !== savedModel
  useDirty(dirty)

  const payload = (p: string, url: string) => ({
    llm_provider: p,
    llm_base_url: p === 'auto' ? '' : url,
    llm_api_key: apiKey, // empty keeps the saved key
    llm_model: model,
  })

  // The select saves at once; it reverts (provider and URL) on failure. A URL belongs to
  // one provider: switching keeps the saved URL only when returning to the saved provider,
  // otherwise the new provider starts at its default address.
  const choose = (next: string) => {
    const previous = { provider, baseUrl }
    const url = next === savedProvider ? savedUrl : ''
    setProvider(next)
    setBaseUrl(url)
    setModels([])
    runSelect(async () => {
      try {
        await saveSettings(addinName, payload(next, url))
      } catch (error) {
        setProvider(previous.provider)
        setBaseUrl(previous.baseUrl)
        throw error
      }
      if (apiKey) setKeySaved(true)
      setApiKey('')
      onSaved({ llm_provider: next, llm_base_url: next === 'auto' ? '' : url, llm_model: model })
    }, 'Saved', "Couldn't change the provider")
  }

  const handleSave = () => runSave(async () => {
    await saveSettings(addinName, payload(provider, baseUrl))
    if (apiKey) setKeySaved(true)
    setApiKey('')
    onSaved({ llm_base_url: baseUrl, llm_model: model })
  })

  const handleTest = () => runTest(async () => {
    const result = await addinsApi.action(addinName, 'test_llm', {
      provider, base_url: baseUrl || LOCAL_DEFAULT_URLS[provider] || '', api_key: apiKey, model,
    })
    if (!result?.success) throw new Error(result?.message || result?.error || 'no response')
    return result
  }, isCloud ? 'Key format looks right (cloud keys are only format-checked)' : 'Connected', 'Test failed')

  const listModels = () => runList(async () => {
    const result = await addinsApi.action(addinName, 'list_models', {
      provider, base_url: baseUrl || LOCAL_DEFAULT_URLS[provider] || '', api_key: apiKey,
    })
    setModels(result?.models || [])
  }, 'Model list refreshed', "Couldn't load models")

  return (
    <div className="rounded-lg border border-dark-border/60 bg-dark-bg-secondary/50 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <h4 className="text-sm font-medium text-dark-text-primary">{section.title}</h4>
        {dirty && <UnsavedPill />}
      </div>
      {section.description && <p className="text-xs text-dark-text-secondary -mt-2">{section.description}</p>}

      <SelectField label={providerField?.label || 'Provider'} value={provider} onChange={choose} options={options}
                   disabled={selectState.status === 'busy'} />
      <ErrorStatus state={selectState} />

      {provider === 'auto' && (
        <p className="text-xs text-dark-text-secondary">Engram looks for LM Studio, then Ollama, on this computer.</p>
      )}
      {isCloud && (
        <InfoNote>
          Not used yet: Skill Voyager currently only uses a local model. The key and model below are saved but ignored.
        </InfoNote>
      )}
      {isLocal && (
        <p className="text-xs text-dark-text-secondary">
          Skill Voyager uses whichever model is loaded on that server; the Model field below is saved but not used yet.
        </p>
      )}

      {isLocal && (
        <TextField label="Server URL" value={baseUrl} onChange={setBaseUrl} placeholder={LOCAL_DEFAULT_URLS[provider]}
                   hint="Don't end it with /v1; Engram adds that itself." />
      )}
      {isCloud && (
        <PasswordField
          label="API key (not used yet)"
          value={apiKey}
          onChange={setApiKey}
          placeholder={keySaved ? 'Saved; leave empty to keep it' : 'sk-...'}
        />
      )}
      {provider !== 'auto' && (
        <div>
          <div className="flex items-end gap-2">
            <div className="flex-1 min-w-0">
              {models.length > 0 ? (
                <SelectField label="Model (not used yet)" value={model} onChange={setModel}
                             options={[...(model && !models.includes(model) ? [model] : []), ...models].map(m => ({ value: m, label: m }))} />
              ) : (
                <TextField label="Model (not used yet)" value={model} onChange={setModel}
                           placeholder={isCloud ? 'gpt-4o-mini' : 'local-model'} />
              )}
            </div>
            {isLocal && (
              <button
                type="button"
                onClick={listModels}
                disabled={listState.status === 'busy'}
                className="inline-flex items-center gap-1 px-2 py-1.5 min-h-[40px] sm:min-h-0 rounded text-xs text-dark-accent-text
                           hover:underline disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-dark-accent-primary"
              >
                <RefreshCw size={12} className={listState.status === 'busy' ? 'animate-spin' : ''} /> Refresh
              </button>
            )}
          </div>
          <ActionStatus state={listState} />
        </div>
      )}

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
    </div>
  )
}

// ------------------------------------------------------------------ General section

function GeneralSection({ addinName, section, saved, onSaved }: {
  addinName: string; section: SettingsSection; saved: Values; onSaved: (patch: Values) => void
}) {
  // Local values for every field in this section (instant fields mirror the server)
  const [values, setValues] = useState<Values>(() =>
    Object.fromEntries(section.fields.map(f => [f.key, saved[f.key]])))
  const [instantState, runInstant] = useAction()
  const [saveState, runSave] = useAction()

  const typedKeys = section.fields.filter(f => !INSTANT.has(f.type)).map(f => f.key)
  const dirtyKeys = typedKeys.filter(k => values[k] !== saved[k] && !(section.fields.find(f => f.key === k)?.type === 'password' && values[k] === ''))
  const dirty = dirtyKeys.length > 0
  useDirty(dirty)

  const visible = (field: SettingsField) => !field.show_when || Object.entries(field.show_when)
    .every(([dep, allowed]) => allowed.includes(values[dep] ?? saved[dep]))

  // Switches, selects and sliders: save just this key now; revert if it fails
  const saveNow = (field: SettingsField, next: unknown) => {
    // A slider's local value has already moved while dragging, so revert to the saved one
    const previous = field.type === 'range' ? saved[field.key] : values[field.key]
    setValues(v => ({ ...v, [field.key]: next }))
    runInstant(async () => {
      try {
        await saveSettings(addinName, { [field.key]: next })
      } catch (error) {
        setValues(v => ({ ...v, [field.key]: previous }))
        throw error
      }
      onSaved({ [field.key]: next })
    }, `${field.label}: saved`, `Couldn't save ${field.label}`)
  }

  const handleSave = () => runSave(async () => {
    const patch = Object.fromEntries(dirtyKeys.map(k => [k, values[k]]))
    await saveSettings(addinName, patch)
    onSaved(patch)
  })

  return (
    <div className="rounded-lg border border-dark-border/60 bg-dark-bg-secondary/50 p-4 space-y-3">
      <div>
        <div className="flex items-center gap-2">
          <h4 className="text-sm font-medium text-dark-text-primary">{section.title}</h4>
          {dirty && <UnsavedPill />}
        </div>
        {section.description && <p className="text-xs text-dark-text-secondary mt-0.5">{section.description}</p>}
      </div>

      {section.fields.filter(visible).map(field => (
        <FieldRenderer
          key={field.key}
          field={field}
          value={values[field.key]}
          onChange={val => (INSTANT.has(field.type) && field.type !== 'range'
            ? saveNow(field, val)
            : setValues(v => ({ ...v, [field.key]: val })))}
          onCommit={field.type === 'range' ? (val) => { if (val !== saved[field.key]) saveNow(field, val) } : undefined}
        />
      ))}
      <ActionStatus state={instantState} />

      {typedKeys.length > 0 && (
        <ActionRow>
          <ActionButton variant="primary" onClick={handleSave} busy={saveState.status === 'busy'} disabled={!dirty}>
            {saveState.status === 'busy' ? 'Saving…' : 'Save'}
          </ActionButton>
          <ActionStatus state={saveState} />
        </ActionRow>
      )}
    </div>
  )
}

/** Renders a single field based on its type. */
function FieldRenderer({ field, value, onChange, onCommit }: {
  field: SettingsField
  value: unknown
  onChange: (val: unknown) => void
  /** Sliders: called when the user lets go */
  onCommit?: (val: unknown) => void
}) {
  switch (field.type) {
    case 'toggle':
      return (
        <div className="flex items-center justify-between gap-3 py-0.5">
          <span className="text-sm text-dark-text-primary">{field.label}</span>
          <Switch checked={!!value} onChange={onChange} label={field.label} />
        </div>
      )

    case 'text':
      return <TextField label={field.label} value={String(value ?? '')} onChange={onChange} placeholder={field.placeholder} />

    case 'password':
      return (
        <PasswordField
          label={field.label}
          value={String(value ?? '')}
          onChange={onChange}
          placeholder={field.is_set ? 'Saved; leave empty to keep it' : field.placeholder}
        />
      )

    case 'select': {
      const options = (field.options || []).map(o => ({ value: String(o.value), label: o.label }))
      return (
        <SelectField
          label={field.label}
          value={String(value ?? field.default ?? '')}
          options={options}
          onChange={v => onChange(field.options?.find(o => String(o.value) === v)?.value ?? v)}
        />
      )
    }

    case 'number':
      return (
        <TextField
          label={field.label}
          type="number"
          value={value === '' || value === undefined || value === null ? '' : String(value)}
          onChange={v => onChange(v === '' ? '' : Number(v))}
          min={field.min}
          max={field.max}
          placeholder={field.placeholder}
        />
      )

    case 'range': {
      const num = Number(value ?? field.default ?? 0)
      const commit = (e: React.SyntheticEvent<HTMLInputElement>) => onCommit?.(Number(e.currentTarget.value))
      return (
        <div>
          <div className="flex items-center justify-between mb-1">
            <label htmlFor={`range-${field.key}`} className="text-xs font-medium text-dark-text-secondary">{field.label}</label>
            <span className="text-xs text-dark-text-primary font-mono">{num.toFixed(2)}</span>
          </div>
          <input
            id={`range-${field.key}`}
            type="range"
            value={String(num)}
            onChange={e => onChange(Number(e.target.value))}
            onPointerUp={commit}
            onKeyUp={commit}
            onBlur={commit}
            min={field.min}
            max={field.max}
            step={field.step}
            className="w-full h-1.5 bg-dark-bg-primary rounded-full appearance-none cursor-pointer accent-dark-accent-primary"
          />
        </div>
      )
    }

    default:
      return null
  }
}
