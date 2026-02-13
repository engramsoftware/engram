/**
 * Add-ins tab for managing plugins.
 * Shows rich cards with type badges, descriptions, permissions,
 * toggle switches, config panels, and uninstall buttons.
 */

import { useState, useEffect } from 'react'
import {
  Wrench,
  Monitor,
  ArrowLeftRight,
  Layers,
  Shield,
  Trash2,
  ChevronDown,
  ChevronUp,
  Loader2,
  Puzzle,
  Package,
} from 'lucide-react'
import { addinsApi } from '../../services/api'
import { useAddinsStore } from '../../stores/addinsStore'
import type { Addin, AddinType } from '../../types/addin.types'

/** Badge colors and icons per addin type. */
const TYPE_META: Record<AddinType, { label: string; color: string; icon: React.ReactNode }> = {
  tool:        { label: 'Tool',        color: 'bg-blue-500/20 text-blue-400 border-blue-500/30',      icon: <Wrench size={12} /> },
  gui:         { label: 'GUI',         color: 'bg-purple-500/20 text-purple-400 border-purple-500/30', icon: <Monitor size={12} /> },
  interceptor: { label: 'Interceptor', color: 'bg-amber-500/20 text-amber-400 border-amber-500/30',   icon: <ArrowLeftRight size={12} /> },
  hybrid:      { label: 'Hybrid',      color: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30', icon: <Layers size={12} /> },
}

/** Human-readable permission labels. */
const PERM_LABELS: Record<string, string> = {
  network: 'Network Access',
  storage: 'File Storage',
  memory: 'Memory System',
  graph: 'Knowledge Graph',
  search: 'Search Engine',
  'llm.messages': 'Message Pipeline',
}

export default function AddinsTab() {
  const [addins, setAddins] = useState<Addin[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [togglingId, setTogglingId] = useState<string | null>(null)
  const [uninstallingId, setUninstallingId] = useState<string | null>(null)

  const fetchAddins = async () => {
    try {
      const data = await addinsApi.list()
      setAddins(data)
    } catch (error) {
      console.error('Failed to fetch add-ins:', error)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => { fetchAddins() }, [])

  // Refresh the global addins store so the sidebar updates when GUI addins are toggled
  const refreshGlobalStore = useAddinsStore(s => s.fetchAddins)

  const handleToggle = async (id: string) => {
    setTogglingId(id)
    try {
      const updated = await addinsApi.toggle(id)
      setAddins(prev => prev.map(a => a.id === id ? { ...a, ...updated } : a))
      refreshGlobalStore()
    } catch (error) {
      console.error('Failed to toggle add-in:', error)
    } finally {
      setTogglingId(null)
    }
  }

  const handleUninstall = async (id: string, name: string) => {
    if (!confirm(`Uninstall "${name}"? This will remove all its settings.`)) return
    setUninstallingId(id)
    try {
      await addinsApi.uninstall(id)
      setAddins(prev => prev.filter(a => a.id !== id))
      refreshGlobalStore()
    } catch (error) {
      console.error('Failed to uninstall add-in:', error)
    } finally {
      setUninstallingId(null)
    }
  }

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 size={24} className="animate-spin text-dark-text-secondary" />
      </div>
    )
  }

  // Sort: enabled first, then alphabetical
  const sorted = [...addins].sort((a, b) => {
    if (a.enabled !== b.enabled) return a.enabled ? -1 : 1
    return a.name.localeCompare(b.name)
  })

  return (
    <div className="h-full overflow-y-auto p-6 max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Puzzle size={24} className="text-dark-accent-primary" />
          <div>
            <h1 className="text-2xl font-semibold text-dark-text-primary">Add-ins</h1>
            <p className="text-sm text-dark-text-secondary mt-0.5">
              {addins.filter(a => a.enabled).length} of {addins.length} enabled
            </p>
          </div>
        </div>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 mb-5">
        {Object.entries(TYPE_META).map(([key, meta]) => (
          <div key={key} className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs border ${meta.color}`}>
            {meta.icon}
            <span>{meta.label}</span>
          </div>
        ))}
      </div>

      {/* Addin cards */}
      <div className="space-y-3">
        {sorted.map((addin) => {
          const meta = TYPE_META[addin.addin_type] || TYPE_META.tool
          const isExpanded = expandedId === addin.id
          const configEntries = Object.entries(addin.config?.settings || {})

          return (
            <div
              key={addin.id}
              className={`rounded-lg border transition-colors ${
                addin.enabled
                  ? 'border-dark-accent-primary/40 bg-dark-bg-secondary'
                  : 'border-dark-border bg-dark-bg-secondary/60'
              }`}
            >
              {/* Main row */}
              <div className="p-4">
                <div className="flex items-start gap-3">
                  {/* Icon */}
                  <div className={`mt-0.5 flex-shrink-0 w-9 h-9 rounded-lg flex items-center justify-center ${meta.color}`}>
                    {meta.icon}
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="text-sm font-semibold text-dark-text-primary">{addin.name}</h3>
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium border ${meta.color}`}>
                        {meta.label}
                      </span>
                      <span className="text-[10px] text-dark-text-secondary">v{addin.version}</span>
                      {addin.built_in && (
                        <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] text-dark-text-secondary bg-dark-bg-primary border border-dark-border">
                          <Package size={9} /> Built-in
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-dark-text-secondary mt-1 leading-relaxed">
                      {addin.description || 'No description available.'}
                    </p>

                    {/* Permissions */}
                    {addin.permissions.length > 0 && (
                      <div className="flex items-center gap-1.5 mt-2 flex-wrap">
                        <Shield size={10} className="text-dark-text-secondary flex-shrink-0" />
                        {addin.permissions.map(p => (
                          <span key={p} className="text-[10px] text-dark-text-secondary bg-dark-bg-primary px-1.5 py-0.5 rounded">
                            {PERM_LABELS[p] || p}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {/* Toggle */}
                    <button
                      type="button"
                      role="switch"
                      aria-checked={addin.enabled}
                      disabled={togglingId === addin.id}
                      onClick={() => handleToggle(addin.id)}
                      className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full
                                 border-2 border-transparent transition-colors duration-200 ease-in-out
                                 disabled:opacity-50
                                 ${addin.enabled ? 'bg-dark-accent-primary' : 'bg-dark-border'}`}
                    >
                      <span
                        className={`pointer-events-none inline-block h-4 w-4 transform rounded-full
                                   bg-white shadow ring-0 transition duration-200 ease-in-out
                                   ${addin.enabled ? 'translate-x-4' : 'translate-x-0'}`}
                      />
                    </button>

                    {/* Expand */}
                    <button
                      onClick={() => setExpandedId(isExpanded ? null : addin.id)}
                      className="p-1 rounded text-dark-text-secondary hover:text-dark-text-primary
                                 hover:bg-dark-bg-primary transition-colors"
                      title="Details"
                    >
                      {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    </button>
                  </div>
                </div>
              </div>

              {/* Expanded details */}
              {isExpanded && (
                <div className="border-t border-dark-border px-4 py-3 space-y-3">
                  {/* Config */}
                  {configEntries.length > 0 && (
                    <div>
                      <h4 className="text-xs font-medium text-dark-text-secondary uppercase tracking-wider mb-2">
                        Configuration
                      </h4>
                      <div className="grid grid-cols-2 gap-2">
                        {configEntries.map(([key, val]) => (
                          <div key={key} className="flex items-center justify-between bg-dark-bg-primary rounded px-3 py-1.5">
                            <span className="text-xs text-dark-text-secondary">{key.replace(/_/g, ' ')}</span>
                            <span className="text-xs text-dark-text-primary font-mono">
                              {typeof val === 'boolean' ? (val ? 'Yes' : 'No') : String(val) || '—'}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* How it works */}
                  <div>
                    <h4 className="text-xs font-medium text-dark-text-secondary uppercase tracking-wider mb-1">
                      How it works
                    </h4>
                    <p className="text-xs text-dark-text-secondary leading-relaxed">
                      {addin.addin_type === 'tool' && 'This add-in registers tools that the AI can call during conversations. When enabled, the AI can invoke these functions automatically when relevant.'}
                      {addin.addin_type === 'gui' && 'This add-in provides a visual interface panel. When enabled, it adds a new tab to the sidebar for direct interaction.'}
                      {addin.addin_type === 'interceptor' && 'This add-in hooks into the message pipeline. It can transform messages before they reach the AI and modify responses before you see them.'}
                      {addin.addin_type === 'hybrid' && 'This add-in combines multiple capabilities: tools, UI panels, and message pipeline hooks.'}
                    </p>
                  </div>

                  {/* Uninstall */}
                  {!addin.built_in && (
                    <div className="flex justify-end pt-1">
                      <button
                        onClick={() => handleUninstall(addin.id, addin.name)}
                        disabled={uninstallingId === addin.id}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs
                                   text-red-400 hover:text-red-300 hover:bg-red-500/10 border border-red-500/20
                                   disabled:opacity-50 transition-colors"
                      >
                        {uninstallingId === addin.id
                          ? <Loader2 size={12} className="animate-spin" />
                          : <Trash2 size={12} />}
                        Uninstall
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}

        {addins.length === 0 && (
          <div className="text-center py-12">
            <Puzzle size={40} className="mx-auto text-dark-text-secondary/40 mb-3" />
            <p className="text-dark-text-secondary">No add-ins installed</p>
            <p className="text-xs text-dark-text-secondary/60 mt-1">Add-ins extend your AI with new capabilities</p>
          </div>
        )}
      </div>
    </div>
  )
}
