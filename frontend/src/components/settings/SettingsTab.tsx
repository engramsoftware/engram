/**
 * Settings tab: section navigation (a rail on desktop, scrollable tabs on
 * phones) with one panel per section. Panels stay mounted while hidden so
 * unsaved input survives switching sections; the last section is remembered.
 */

import { useState, useEffect, useRef, type KeyboardEvent, type ReactNode } from 'react'
import {
  Settings, Cloud, Monitor, Globe, Mail, ScrollText,
  Database, Upload, Download, Check, Loader2, Zap, Puzzle,
} from 'lucide-react'
import { useAuthStore } from '../../stores/authStore'
import { useAddinsStore } from '../../stores/addinsStore'
import { useUIStore } from '../../stores/uiStore'
import { settingsApi, addinsApi } from '../../services/api'
import type { LLMSettings } from '../../types/chat.types'
import type { Addin } from '../../types/addin.types'
import ProviderSettings from './ProviderSettings'
import BraveSearchSettings from './BraveSearchSettings'
import Neo4jSettings from './Neo4jSettings'
import EmailSettings from './EmailSettings'
import OptimizationSettings from './OptimizationSettings'
import LoggingSettings from './LoggingSettings'
import LogViewer from './LogViewer'
import AddinSettingsRenderer from './AddinSettingsRenderer'
import { ActionButton, ActionStatus, Badge, SettingsCard, useAction } from './primitives'

/** Providers that run locally and don't need an API key */
const LOCAL_PROVIDERS = new Set(['lmstudio', 'ollama'])

/** Provider display names for the header subtitle */
const PROVIDER_DISPLAY: Record<string, string> = {
  openai: 'OpenAI', anthropic: 'Anthropic',
  lmstudio: 'LM Studio', ollama: 'Ollama',
}

const SECTIONS: { id: string; label: string; icon: ReactNode; description: string }[] = [
  { id: 'models', label: 'Models', icon: <Cloud size={16} />, description: 'Choose the LLM provider and default model. One provider is active at a time.' },
  { id: 'search', label: 'Search & Graph', icon: <Globe size={16} />, description: 'Web search and the knowledge graph store.' },
  { id: 'email', label: 'Email', icon: <Mail size={16} />, description: 'Reminders, summaries and alerts sent to your inbox.' },
  { id: 'performance', label: 'Performance', icon: <Zap size={16} />, description: 'Response validation and token savings.' },
  { id: 'addins', label: 'Add-ins', icon: <Puzzle size={16} />, description: 'Turn add-ins on or off and configure the ones that have settings.' },
  { id: 'system', label: 'System', icon: <ScrollText size={16} />, description: 'Log levels, the live log viewer, and data import/export.' },
]

export default function SettingsTab() {
  const [settings, setSettings] = useState<LLMSettings | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const { settingsSection, setSettingsSection } = useUIStore()
  const section = SECTIONS.some(s => s.id === settingsSection) ? settingsSection : 'models'
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({})

  const refreshSettings = async () => {
    try {
      const data = await settingsApi.getLLMSettings()
      setSettings(data)
      setLoadError(false)
    } catch (error) {
      console.error('Failed to fetch settings:', error)
      setLoadError(true)
    }
  }

  const load = () => {
    setIsLoading(true)
    refreshSettings().finally(() => setIsLoading(false))
  }

  useEffect(load, [])

  // Fetch addins for the Add-ins section
  const { addins, loaded: addinsLoaded, fetchAddins } = useAddinsStore()
  useEffect(() => { if (!addinsLoaded) fetchAddins() }, [addinsLoaded, fetchAddins])

  // Arrow keys / Home / End move between section tabs (roving tabindex)
  const onTabKeyDown = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next: number
    if (e.key === 'ArrowDown' || e.key === 'ArrowRight') next = index + 1
    else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') next = index - 1
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = SECTIONS.length - 1
    else return
    e.preventDefault()
    const target = SECTIONS[(next + SECTIONS.length) % SECTIONS.length]
    setSettingsSection(target.id)
    tabRefs.current[target.id]?.focus()
  }

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-6 h-6 border-2 border-dark-accent-primary border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-dark-text-secondary">Loading settings...</p>
        </div>
      </div>
    )
  }

  if (loadError && !settings) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3 px-4 text-center">
        <p className="text-sm text-dark-text-secondary">Couldn't load your settings.</p>
        <ActionButton onClick={load}>Retry</ActionButton>
      </div>
    )
  }

  const providers = settings?.available_providers || []
  const cloudProviders = providers.filter(p => !LOCAL_PROVIDERS.has(p))
  const localProviders = providers.filter(p => LOCAL_PROVIDERS.has(p))
  const activeProvider = providers.find(p => settings?.providers[p]?.enabled) || null
  const enabledAddins = addins.filter(a => a.enabled).length

  const providerGroup = (label: string, icon: ReactNode, list: string[]) => list.length > 0 && (
    <div>
      <div className="flex items-center gap-2 mb-2 text-dark-text-secondary">
        {icon}
        <span className="text-[10px] font-semibold uppercase tracking-wider">{label}</span>
      </div>
      <div className="space-y-2">
        {list.map(provider => (
          <ProviderSettings
            key={provider}
            provider={provider}
            config={settings!.providers[provider]}
            defaultModel={settings?.default_model}
            onUpdate={refreshSettings}
          />
        ))}
      </div>
    </div>
  )

  const panels: Record<string, ReactNode> = {
    models: (
      <div className="space-y-5">
        {!activeProvider && (
          <p className="text-xs text-dark-text-secondary">No provider is enabled yet. Turn one on to start chatting.</p>
        )}
        {providerGroup('Cloud API', <Cloud size={12} />, cloudProviders)}
        {providerGroup('Local', <Monitor size={12} />, localProviders)}
      </div>
    ),
    search: (
      <div className="space-y-3">
        <BraveSearchSettings config={settings?.brave_search} onUpdate={refreshSettings} />
        <Neo4jSettings config={settings?.neo4j} onUpdate={refreshSettings} />
      </div>
    ),
    email: <EmailSettings config={settings?.email} onUpdate={refreshSettings} />,
    performance: <OptimizationSettings config={settings?.optimization} onUpdate={refreshSettings} />,
    addins: <AddinsSettings addins={addins} onRefresh={fetchAddins} />,
    system: (
      <div className="space-y-3">
        <SettingsCard title="Logging" subtitle="Log levels and live log viewer" icon={<ScrollText size={14} />}>
          <LoggingSettings />
          {/* Only stream logs while this section is on screen */}
          {section === 'system' && <LogViewer />}
        </SettingsCard>
        <SettingsCard title="Data management" subtitle="Import and export your data" icon={<Database size={14} />} defaultOpen>
          <DataManagement />
        </SettingsCard>
      </div>
    ),
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
        {/* Header */}
        <div className="flex items-center gap-3 mb-5">
          <div className="p-2 rounded-lg bg-dark-accent-primary/10">
            <Settings size={20} className="text-dark-accent-primary" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-dark-text-primary">Settings</h1>
            <p className="text-sm text-dark-text-secondary">
              {activeProvider
                ? <>LLM: <span className="text-dark-text-primary font-medium">{PROVIDER_DISPLAY[activeProvider] || activeProvider}</span></>
                : 'No LLM provider active'
              }
              {enabledAddins > 0 && (
                <span className="ml-2">· {enabledAddins} add-in{enabledAddins !== 1 ? 's' : ''} active</span>
              )}
            </p>
          </div>
        </div>

        <div className="md:flex md:items-start md:gap-6">
          {/* Section navigation: scrollable tabs on phones, a rail on desktop */}
          <div
            role="tablist"
            aria-label="Settings sections"
            className="sticky top-0 z-10 -mx-4 px-4 py-2 mb-3 flex gap-1 overflow-x-auto bg-dark-bg-primary
                       md:mx-0 md:px-0 md:py-0 md:mb-0 md:flex-col md:w-48 md:flex-shrink-0 md:overflow-visible md:bg-transparent"
          >
            {SECTIONS.map((s, i) => {
              const selected = s.id === section
              return (
                <button
                  key={s.id}
                  ref={el => { tabRefs.current[s.id] = el }}
                  role="tab"
                  id={`settings-tab-${s.id}`}
                  aria-selected={selected}
                  aria-controls={`settings-panel-${s.id}`}
                  tabIndex={selected ? 0 : -1}
                  onClick={() => setSettingsSection(s.id)}
                  onKeyDown={e => onTabKeyDown(e, i)}
                  className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm whitespace-nowrap flex-shrink-0
                              transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-dark-accent-primary ${
                    selected
                      ? 'bg-dark-bg-secondary text-dark-text-primary font-medium'
                      : 'text-dark-text-secondary hover:bg-dark-bg-secondary hover:text-dark-text-primary'
                  }`}
                >
                  {s.icon}
                  <span>{s.label}</span>
                </button>
              )
            })}
          </div>

          {/* Panels stay mounted (hidden) so unsaved input survives switching sections */}
          <div className="flex-1 min-w-0 pb-12">
            {SECTIONS.map(s => (
              <div
                key={s.id}
                role="tabpanel"
                id={`settings-panel-${s.id}`}
                aria-labelledby={`settings-tab-${s.id}`}
                hidden={s.id !== section}
              >
                <div className="mb-4">
                  <h2 className="text-base font-semibold text-dark-text-primary">{s.label}</h2>
                  <p className="text-xs text-dark-text-secondary mt-0.5">{s.description}</p>
                </div>
                {panels[s.id]}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}


const TYPE_LABELS: Record<string, string> = {
  tool: 'Tool',
  gui: 'GUI',
  interceptor: 'Pipeline',
  hybrid: 'Hybrid',
}

/**
 * Addins settings — one card per add-in with an enable switch and its
 * dynamic settings. Each addin declares its own settings schema via
 * get_settings_schema(); the renderer discovers and renders them generically.
 */
function AddinsSettings({ addins, onRefresh }: { addins: Addin[]; onRefresh: () => void }) {
  const [toggleState, runToggle] = useAction()
  const [busyId, setBusyId] = useState<string | null>(null)

  const handleToggle = (addin: Addin) => {
    setBusyId(addin.id)
    runToggle(async () => {
      await addinsApi.toggle(addin.id)
      onRefresh()
    }, `${addin.name} ${addin.enabled ? 'disabled' : 'enabled'}`, `Couldn't change ${addin.name}`)
      .finally(() => setBusyId(null))
  }

  if (addins.length === 0) {
    return (
      <p className="text-xs text-dark-text-secondary italic py-2">
        No add-ins installed. Add-ins appear here when placed in the plugins directory.
      </p>
    )
  }

  return (
    <div className="space-y-2">
      <ActionStatus state={toggleState} />
      {addins.map(addin => (
        <SettingsCard
          key={addin.internal_name || addin.id}
          title={addin.name}
          subtitle={addin.description}
          badges={<>
            <Badge>{TYPE_LABELS[addin.addin_type] || addin.addin_type}</Badge>
            <span className="text-[10px] text-dark-text-secondary">v{addin.version}</span>
          </>}
          enabled={addin.enabled}
          onToggle={() => handleToggle(addin)}
          toggleDisabled={busyId === addin.id}
        >
          {addin.enabled
            ? <AddinSettingsRenderer addinName={addin.internal_name} />
            : <p className="text-xs text-dark-text-secondary italic">Enable this add-in to configure its settings.</p>}
        </SettingsCard>
      ))}
    </div>
  )
}


/** Import/Export panel for user data. */
function DataManagement() {
  const fileRef = useRef<HTMLInputElement>(null)
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<string | null>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const [exportState, runExport] = useAction()

  const token = useAuthStore.getState().token

  /** Handle ChatGPT import file selection */
  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setImporting(true)
    setImportResult(null)
    setImportError(null)

    try {
      const formData = new FormData()
      formData.append('file', file)

      const res = await fetch('/api/data/import/chatgpt', {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      })

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Import failed' }))
        throw new Error(err.detail || 'Import failed')
      }

      const data = await res.json()
      setImportResult(
        `Imported ${data.imported.conversations} conversations with ${data.imported.messages} messages` +
        (data.skipped > 0 ? ` (${data.skipped} empty skipped)` : '')
      )
    } catch (err) {
      setImportError(err instanceof Error ? err.message : 'Import failed')
    } finally {
      setImporting(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  /** Download full data export as ZIP */
  const handleExport = () => runExport(async () => {
    const res = await fetch('/api/data/export', {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!res.ok) throw new Error(`server returned ${res.status}`)

    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = res.headers.get('content-disposition')?.match(/filename="(.+)"/)?.[1] || 'engram_export.zip'
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }, 'Export downloaded', 'Export failed')

  return (
    <div className="space-y-3">
      {/* ChatGPT Import */}
      <div className="rounded-lg border border-dark-border bg-dark-bg-primary/40 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-medium text-dark-text-primary">Import from ChatGPT</h3>
            <p className="text-xs text-dark-text-secondary mt-1">
              Upload your ChatGPT export (ZIP or conversations.json) to import all conversations.
            </p>
          </div>
          <div className="flex-shrink-0">
            <input
              ref={fileRef}
              type="file"
              accept=".zip,.json"
              onChange={handleImport}
              className="sr-only"
              id="chatgpt-import"
            />
            <label
              htmlFor="chatgpt-import"
              className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium
                         cursor-pointer transition-colors
                         ${importing
                           ? 'bg-dark-border text-dark-text-secondary cursor-wait'
                           : 'bg-dark-accent-primary hover:bg-dark-accent-hover text-white'}`}
            >
              {importing ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
              {importing ? 'Importing...' : 'Import'}
            </label>
          </div>
        </div>
        {importResult && (
          <div role="status" className="mt-3 p-2 rounded bg-green-500/10 border border-green-500/30 text-green-400 [.light_&]:text-green-700 text-xs flex items-center gap-2">
            <Check size={14} />
            {importResult}
          </div>
        )}
        {importError && (
          <div role="alert" className="mt-3 p-2 rounded bg-red-500/10 border border-red-500/30 text-red-400 [.light_&]:text-red-700 text-xs">
            {importError}
          </div>
        )}
      </div>

      {/* Export All Data */}
      <div className="rounded-lg border border-dark-border bg-dark-bg-primary/40 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-medium text-dark-text-primary">Export all data</h3>
            <p className="text-xs text-dark-text-secondary mt-1">
              Download all your conversations, memories, notes, and settings as a ZIP file.
            </p>
            <div className="mt-1"><ActionStatus state={exportState} /></div>
          </div>
          <ActionButton onClick={handleExport} busy={exportState.status === 'busy'}>
            {exportState.status !== 'busy' && <Download size={14} />}
            {exportState.status === 'busy' ? 'Exporting...' : 'Export'}
          </ActionButton>
        </div>
      </div>
    </div>
  )
}
