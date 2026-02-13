/**
 * Brave Search API settings card.
 * Allows users to configure their Brave Search API key for web search.
 *
 * @param config - Current Brave Search configuration from the backend
 * @param onUpdate - Callback to refresh parent settings after save
 */

import { useState } from 'react'
import {
  Check, X, Globe, Loader2, ChevronDown, ChevronRight, Zap
} from 'lucide-react'
import { settingsApi } from '../../services/api'
import type { BraveSearchConfig } from '../../types/chat.types'

interface Props {
  config?: BraveSearchConfig
  onUpdate: () => void
}

export default function BraveSearchSettings({ config, onUpdate }: Props) {
  const [apiKey, setApiKey] = useState('')
  const [isEnabled, setIsEnabled] = useState(config?.enabled || false)
  const [isTesting, setIsTesting] = useState(false)
  const [testResult, setTestResult] = useState<boolean | null>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [isExpanded, setIsExpanded] = useState(config?.enabled || false)

  const handleToggle = async (e: React.MouseEvent) => {
    e.stopPropagation()
    const next = !isEnabled
    setIsEnabled(next)
    if (next) setIsExpanded(true)
    // Auto-save toggle
    try {
      await settingsApi.updateLLMSettings({
        brave_search: {
          enabled: next,
          api_key: apiKey || undefined,
        }
      })
      onUpdate()
    } catch (error) {
      console.error('Failed to toggle Brave Search:', error)
      setIsEnabled(!next)
    }
  }

  const handleSave = async () => {
    setIsSaving(true)
    try {
      await settingsApi.updateLLMSettings({
        brave_search: {
          enabled: isEnabled,
          api_key: apiKey || undefined,
        }
      })
      onUpdate()
    } catch (error) {
      console.error('Failed to save Brave Search settings:', error)
    } finally {
      setIsSaving(false)
    }
  }

  const handleTest = async () => {
    setIsTesting(true)
    setTestResult(null)
    try {
      const result = await settingsApi.testBraveSearch(apiKey || undefined)
      setTestResult(result.success)
    } catch {
      setTestResult(false)
    } finally {
      setIsTesting(false)
    }
  }

  return (
    <div className={`rounded-lg border transition-colors ${
      isEnabled
        ? 'bg-dark-bg-secondary border-dark-accent-primary/30'
        : 'bg-dark-bg-secondary/50 border-dark-border/50'
    }`}>
      {/* Header row */}
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
            <Globe size={14} className="text-dark-text-secondary flex-shrink-0" />
            <span className={`text-sm font-medium ${isEnabled ? 'text-dark-text-primary' : 'text-dark-text-secondary'}`}>
              Brave Search
            </span>
            {isEnabled && (
              <span className="flex items-center gap-1 text-[10px] font-medium text-green-400 bg-green-400/10 px-1.5 py-0.5 rounded-full">
                <Zap size={8} /> Active
              </span>
            )}
          </div>
          <p className="text-xs text-dark-text-secondary truncate">
            Web search for real-time info (free tier: 1 req/sec)
          </p>
        </div>

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
          {/* Info */}
          <div className="text-xs text-dark-text-secondary bg-dark-bg-primary/60 rounded-md px-3 py-2">
            Get a free API key at{' '}
            <a
              href="https://api-dashboard.search.brave.com/app/keys"
              target="_blank"
              rel="noopener noreferrer"
              className="text-dark-accent-primary hover:underline"
            >
              api-dashboard.search.brave.com
            </a>
            . Free tier: 2,000 queries/month, 1 query/second.
          </div>

          {/* API Key */}
          <div>
            <label className="text-xs font-medium text-dark-text-secondary block mb-1">API Key</label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={config?.api_key_set ? '••••••••••••' : 'BSA...'}
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
