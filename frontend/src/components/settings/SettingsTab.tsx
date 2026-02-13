/**
 * Settings tab — all sections collapsible, single active LLM provider,
 * dedicated Addins settings area.
 */

import { useState, useEffect, useRef } from 'react'
import {
  Settings, Cloud, Monitor, ScrollText,
  Database, Upload, Download, Check, Loader2, Zap, Puzzle,
  ChevronDown, ChevronRight,
} from 'lucide-react'
import { useAuthStore } from '../../stores/authStore'
import { useAddinsStore } from '../../stores/addinsStore'
import { settingsApi, addinsApi } from '../../services/api'
import type { LLMSettings } from '../../types/chat.types'
import CollapsibleSection from './CollapsibleSection'
import ProviderSettings from './ProviderSettings'
import BraveSearchSettings from './BraveSearchSettings'
import Neo4jSettings from './Neo4jSettings'
import EmailSettings from './EmailSettings'
import OptimizationSettings from './OptimizationSettings'
import LoggingSettings from './LoggingSettings'
import LogViewer from './LogViewer'
import AddinSettingsRenderer from './AddinSettingsRenderer'

/** Providers that run locally and don't need an API key */
const LOCAL_PROVIDERS = new Set(['lmstudio', 'ollama'])


export default function SettingsTab() {
  const [settings, setSettings] = useState<LLMSettings | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const refreshSettings = async () => {
    try {
      const data = await settingsApi.getLLMSettings()
      setSettings(data)
    } catch (error) {
      console.error('Failed to fetch settings:', error)
    }
  }

  useEffect(() => {
    refreshSettings().finally(() => setIsLoading(false))
  }, [])

  // Fetch addins for settings panel
  const { addins, loaded: addinsLoaded, fetchAddins } = useAddinsStore()
  useEffect(() => { if (!addinsLoaded) fetchAddins() }, [addinsLoaded, fetchAddins])

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

  const providers = settings?.available_providers || []
  const cloudProviders = providers.filter(p => !LOCAL_PROVIDERS.has(p))
  const localProviders = providers.filter(p => LOCAL_PROVIDERS.has(p))

  // Find the single active provider
  const activeProvider = providers.find(p => settings?.providers[p]?.enabled) || null

  /** Provider display names for the header subtitle */
  const PROVIDER_DISPLAY: Record<string, string> = {
    openai: 'OpenAI', anthropic: 'Anthropic',
    lmstudio: 'LM Studio', ollama: 'Ollama',
  }

  const enabledAddins = addins.filter(a => a.enabled).length

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-2xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 rounded-lg bg-dark-accent-primary/10">
            <Settings size={20} className="text-dark-accent-primary" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-dark-text-primary">Settings</h1>
            <p className="text-sm text-dark-text-secondary">
              {activeProvider
                ? <>LLM: <span className="text-dark-accent-primary font-medium">{PROVIDER_DISPLAY[activeProvider] || activeProvider}</span></>
                : 'No LLM provider active'
              }
              {enabledAddins > 0 && (
                <span className="ml-2 text-dark-text-secondary/60">
                  · {enabledAddins} addin{enabledAddins !== 1 ? 's' : ''} active
                </span>
              )}
            </p>
          </div>
        </div>

        {/* ── LLM Providers ── */}
        <CollapsibleSection
          title="LLM Providers"
          subtitle={activeProvider
            ? `Active: ${PROVIDER_DISPLAY[activeProvider] || activeProvider}`
            : 'No provider enabled — choose one'}
          icon={<Cloud size={16} />}
          defaultOpen={true}
          badge={activeProvider ? 'connected' : undefined}
          badgeColor="green"
        >
          <div className="space-y-4">
            {/* Cloud */}
            {cloudProviders.length > 0 && (
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <Cloud size={12} className="text-dark-text-secondary/60" />
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-dark-text-secondary/60">
                    Cloud API
                  </span>
                </div>
                <div className="space-y-2">
                  {cloudProviders.map(provider => (
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
            )}

            {/* Local */}
            {localProviders.length > 0 && (
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <Monitor size={12} className="text-dark-text-secondary/60" />
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-dark-text-secondary/60">
                    Local
                  </span>
                </div>
                <div className="space-y-2">
                  {localProviders.map(provider => (
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
            )}
          </div>
        </CollapsibleSection>

        {/* ── Web Search ── */}
        <div className="mt-4">
          <BraveSearchSettings
            config={settings?.brave_search}
            onUpdate={refreshSettings}
          />
        </div>

        {/* ── Knowledge Graph ── */}
        <div className="mt-4">
          <Neo4jSettings
            config={settings?.neo4j}
            onUpdate={refreshSettings}
          />
        </div>

        {/* ── Notifications ── */}
        <div className="mt-4">
          <EmailSettings
            config={settings?.email}
            onUpdate={refreshSettings}
          />
        </div>

        {/* ── Optimization ── */}
        <div className="mt-4">
          <CollapsibleSection
            title="Optimization"
            subtitle="Response validation and token savings"
            icon={<Zap size={16} />}
          >
            <OptimizationSettings
              config={settings?.optimization}
              onUpdate={refreshSettings}
            />
          </CollapsibleSection>
        </div>

        {/* ── Add-ins ── */}
        <div className="mt-4">
          <CollapsibleSection
            title="Add-ins"
            subtitle={`${addins.length} installed, ${enabledAddins} active`}
            icon={<Puzzle size={16} />}
            badge={enabledAddins > 0 ? `${enabledAddins} active` : undefined}
            badgeColor="blue"
          >
            <AddinsSettings addins={addins} onRefresh={fetchAddins} />
          </CollapsibleSection>
        </div>

        {/* ── Logging ── */}
        <div className="mt-4">
          <CollapsibleSection
            title="Logging"
            subtitle="Log levels and live log viewer"
            icon={<ScrollText size={16} />}
          >
            <LoggingSettings />
            <div className="mt-4">
              <LogViewer />
            </div>
          </CollapsibleSection>
        </div>

        {/* ── Data Management ── */}
        <div className="mt-4 mb-12">
          <CollapsibleSection
            title="Data Management"
            subtitle="Import and export your data"
            icon={<Database size={16} />}
          >
            <DataManagement />
          </CollapsibleSection>
        </div>
      </div>
    </div>
  )
}


/**
 * Addins settings — expandable cards with toggle + dynamic settings.
 * Each addin declares its own settings schema via get_settings_schema().
 * The renderer discovers and renders them generically — nothing is hardcoded
 * per addin. If an addin has no schema, only the enable toggle shows.
 */
function AddinsSettings({ addins, onRefresh }: { addins: any[]; onRefresh: () => void }) {
  const [toggling, setToggling] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  const handleToggle = async (e: React.MouseEvent, addinId: string) => {
    e.stopPropagation()
    setToggling(addinId)
    try {
      await addinsApi.toggle(addinId)
      onRefresh()
    } catch (err) {
      console.error('Failed to toggle addin:', err)
    } finally {
      setToggling(null)
    }
  }

  if (addins.length === 0) {
    return (
      <p className="text-xs text-dark-text-secondary/50 italic py-2">
        No add-ins installed. Add-ins appear here when placed in the plugins directory.
      </p>
    )
  }

  const TYPE_LABELS: Record<string, string> = {
    tool: 'Tool',
    gui: 'GUI',
    interceptor: 'Pipeline',
    hybrid: 'Hybrid',
  }

  return (
    <div className="space-y-2">
      {addins.map(addin => {
        const isExpanded = expanded === addin.internal_name
        return (
          <div
            key={addin.internal_name || addin.id}
            className={`rounded-lg border transition-colors overflow-hidden ${
              addin.enabled
                ? 'border-dark-accent-primary/20 bg-dark-bg-primary/40'
                : 'border-dark-border/30 bg-dark-bg-primary/20'
            }`}
          >
            {/* Header — click to expand, toggle on the right */}
            <div
              className="flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-dark-bg-primary/60 transition-colors"
              onClick={() => setExpanded(isExpanded ? null : addin.internal_name)}
            >
              {/* Chevron */}
              {isExpanded
                ? <ChevronDown size={12} className="text-dark-text-secondary flex-shrink-0" />
                : <ChevronRight size={12} className="text-dark-text-secondary flex-shrink-0" />
              }

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className={`text-sm font-medium ${
                    addin.enabled ? 'text-dark-text-primary' : 'text-dark-text-secondary'
                  }`}>
                    {addin.name}
                  </span>
                  <span className="text-[10px] text-dark-text-secondary/50 bg-dark-bg-primary px-1.5 py-0.5 rounded">
                    {TYPE_LABELS[addin.addin_type] || addin.addin_type}
                  </span>
                  <span className="text-[10px] text-dark-text-secondary/40">
                    v{addin.version}
                  </span>
                </div>
                {addin.description && (
                  <p className="text-[11px] text-dark-text-secondary/60 truncate mt-0.5">
                    {addin.description}
                  </p>
                )}
              </div>

              {/* Toggle */}
              <button
                onClick={(e) => handleToggle(e, addin.id)}
                disabled={toggling === addin.id}
                className={`relative inline-flex items-center w-9 h-5 rounded-full transition-colors flex-shrink-0 ${
                  addin.enabled ? 'bg-dark-accent-primary' : 'bg-dark-border'
                } ${toggling === addin.id ? 'opacity-50' : ''}`}
              >
                <span className={`inline-block w-3.5 h-3.5 rounded-full bg-white shadow-sm transition-transform ${
                  addin.enabled ? 'translate-x-[18px]' : 'translate-x-[3px]'
                }`} />
              </button>
            </div>

            {/* Expanded: dynamic settings from addin's schema */}
            {isExpanded && addin.enabled && (
              <div className="px-3 pb-3 border-t border-dark-border/20">
                <AddinSettingsRenderer addinName={addin.internal_name} />
              </div>
            )}

            {isExpanded && !addin.enabled && (
              <div className="px-3 pb-3 border-t border-dark-border/20">
                <p className="text-[10px] text-dark-text-secondary/40 italic py-2">
                  Enable this add-in to configure its settings.
                </p>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}


/** Import/Export panel for user data. */
function DataManagement() {
  const fileRef = useRef<HTMLInputElement>(null)
  const [importing, setImporting] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [importResult, setImportResult] = useState<string | null>(null)
  const [importError, setImportError] = useState<string | null>(null)

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
  const handleExport = async () => {
    setExporting(true)
    try {
      const res = await fetch('/api/data/export', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!res.ok) throw new Error('Export failed')

      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = res.headers.get('content-disposition')?.match(/filename="(.+)"/)?.[1] || 'engram_export.zip'
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('Export failed:', err)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="space-y-3">
      {/* ChatGPT Import */}
      <div className="rounded-lg border border-dark-border bg-dark-bg-secondary p-4">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-sm font-medium text-dark-text-primary">Import from ChatGPT</h3>
            <p className="text-xs text-dark-text-secondary mt-1">
              Upload your ChatGPT export (ZIP or conversations.json) to import all conversations.
            </p>
          </div>
          <div>
            <input
              ref={fileRef}
              type="file"
              accept=".zip,.json"
              onChange={handleImport}
              className="hidden"
              id="chatgpt-import"
            />
            <label
              htmlFor="chatgpt-import"
              className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium
                         cursor-pointer transition-colors
                         ${importing
                           ? 'bg-dark-border text-dark-text-secondary cursor-wait'
                           : 'bg-indigo-600 hover:bg-indigo-500 text-white'}`}
            >
              {importing ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
              {importing ? 'Importing...' : 'Import'}
            </label>
          </div>
        </div>
        {importResult && (
          <div className="mt-3 p-2 rounded bg-green-500/10 border border-green-500/30 text-green-400 text-xs flex items-center gap-2">
            <Check size={14} />
            {importResult}
          </div>
        )}
        {importError && (
          <div className="mt-3 p-2 rounded bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
            {importError}
          </div>
        )}
      </div>

      {/* Export All Data */}
      <div className="rounded-lg border border-dark-border bg-dark-bg-secondary p-4">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-sm font-medium text-dark-text-primary">Export All Data</h3>
            <p className="text-xs text-dark-text-secondary mt-1">
              Download all your conversations, memories, notes, and settings as a ZIP file.
            </p>
          </div>
          <button
            onClick={handleExport}
            disabled={exporting}
            className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium
                       transition-colors
                       ${exporting
                         ? 'bg-dark-border text-dark-text-secondary cursor-wait'
                         : 'bg-dark-bg-primary hover:bg-dark-border text-dark-text-primary border border-dark-border'}`}
          >
            {exporting ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
            {exporting ? 'Exporting...' : 'Export'}
          </button>
        </div>
      </div>
    </div>
  )
}
