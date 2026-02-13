/**
 * Neo4j Knowledge Graph settings card.
 * Collapsible card with enable toggle, URI, username, password,
 * database fields, and a test connection button.
 *
 * @param config - Current Neo4j config from the backend (may be undefined)
 * @param onUpdate - Callback to refresh parent settings after save
 */

import { useState, useEffect } from 'react'
import {
  Check, X, RefreshCw, ChevronDown, ChevronRight,
  Loader2, Share2,
} from 'lucide-react'
import { settingsApi } from '../../services/api'
import type { Neo4jConfig } from '../../types/chat.types'

interface Props {
  config?: Neo4jConfig
  onUpdate: () => void
}

export default function Neo4jSettings({ config, onUpdate }: Props) {
  const [isEnabled, setIsEnabled] = useState(config?.enabled || false)
  const [isExpanded, setIsExpanded] = useState(config?.enabled || false)
  const [uri, setUri] = useState(config?.uri || '')
  const [username, setUsername] = useState(config?.username || 'neo4j')
  const [password, setPassword] = useState('')
  const [database, setDatabase] = useState(config?.database || 'neo4j')
  const [isSaving, setIsSaving] = useState(false)
  const [isTesting, setIsTesting] = useState(false)
  const [testResult, setTestResult] = useState<boolean | null>(null)
  const [saveSuccess, setSaveSuccess] = useState(false)

  useEffect(() => {
    setIsEnabled(config?.enabled || false)
    setUri(config?.uri || '')
    setUsername(config?.username || 'neo4j')
    setDatabase(config?.database || 'neo4j')
  }, [config?.enabled, config?.uri, config?.username, config?.database])

  /** Toggle enable/disable and auto-save. */
  const handleToggle = async (e: React.MouseEvent) => {
    e.stopPropagation()
    const next = !isEnabled
    setIsEnabled(next)
    if (next) setIsExpanded(true)
    try {
      await settingsApi.updateLLMSettings({
        neo4j: {
          enabled: next,
          uri: uri || undefined,
          username: username || undefined,
          database,
        },
      })
      onUpdate()
    } catch (error) {
      console.error('Failed to toggle Neo4j:', error)
      setIsEnabled(!next)
    }
  }

  /** Save all Neo4j settings. */
  const handleSave = async () => {
    setIsSaving(true)
    setSaveSuccess(false)
    try {
      await settingsApi.updateLLMSettings({
        neo4j: {
          enabled: isEnabled,
          uri: uri || undefined,
          username: username || undefined,
          password: password || undefined,
          database,
        },
      })
      setPassword('')
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 2000)
      onUpdate()
    } catch (error) {
      console.error('Failed to save Neo4j settings:', error)
    } finally {
      setIsSaving(false)
    }
  }

  /** Test Neo4j connection. */
  const handleTest = async () => {
    setIsTesting(true)
    setTestResult(null)
    try {
      const result = await settingsApi.testNeo4j(
        uri || undefined,
        username || undefined,
        password || undefined,
        database || undefined,
      )
      setTestResult(result.success)
    } catch {
      setTestResult(false)
    } finally {
      setIsTesting(false)
    }
  }

  return (
    <div className="rounded-xl border border-dark-border bg-dark-bg-secondary/50 overflow-hidden">
      {/* Header row */}
      <div
        className="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-dark-bg-secondary/80 transition-colors"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3 min-w-0">
          <button
            onClick={(e) => { e.stopPropagation(); setIsExpanded(!isExpanded) }}
            className="text-dark-text-secondary"
          >
            {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
          </button>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Share2 size={14} className="text-dark-text-secondary flex-shrink-0" />
              <span className="text-sm font-medium text-dark-text-primary">
                Neo4j Knowledge Graph
              </span>
              {config?.password_set && (
                <span className="text-[10px] text-green-400 bg-green-400/10 px-1.5 py-0.5 rounded-full">
                  configured
                </span>
              )}
            </div>
            <p className="text-xs text-dark-text-secondary truncate">
              Entity relationships and knowledge graph storage
            </p>
          </div>
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
            Connect to Neo4j Aura (cloud) or a local Neo4j instance for knowledge graph features.
            Get a free instance at{' '}
            <a
              href="https://neo4j.com/cloud/aura-free/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-dark-accent-primary hover:underline"
            >
              neo4j.com/cloud/aura-free
            </a>
          </div>

          {/* URI */}
          <div>
            <label className="block text-xs text-dark-text-secondary mb-1">
              Connection URI
            </label>
            <input
              type="text"
              value={uri}
              onChange={(e) => setUri(e.target.value)}
              placeholder="neo4j+s://xxxxx.databases.neo4j.io"
              className="w-full bg-dark-bg-primary border border-dark-border rounded-md
                         px-3 py-1.5 text-sm text-dark-text-primary placeholder:text-dark-text-secondary/40
                         focus:outline-none focus:border-dark-accent-primary"
            />
          </div>

          {/* Username + Database row */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-xs text-dark-text-secondary mb-1">
                Username
              </label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="neo4j"
                className="w-full bg-dark-bg-primary border border-dark-border rounded-md
                           px-3 py-1.5 text-sm text-dark-text-primary placeholder:text-dark-text-secondary/40
                           focus:outline-none focus:border-dark-accent-primary"
              />
            </div>
            <div>
              <label className="block text-xs text-dark-text-secondary mb-1">
                Database
              </label>
              <input
                type="text"
                value={database}
                onChange={(e) => setDatabase(e.target.value)}
                placeholder="neo4j"
                className="w-full bg-dark-bg-primary border border-dark-border rounded-md
                           px-3 py-1.5 text-sm text-dark-text-primary placeholder:text-dark-text-secondary/40
                           focus:outline-none focus:border-dark-accent-primary"
              />
            </div>
          </div>

          {/* Password */}
          <div>
            <label className="block text-xs text-dark-text-secondary mb-1">
              Password {config?.password_set && !password && (
                <span className="text-dark-text-secondary/60">
                  ({config.password_masked} — leave empty to keep)
                </span>
              )}
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={config?.password_set ? '••••••••' : 'Enter password'}
              className="w-full bg-dark-bg-primary border border-dark-border rounded-md
                         px-3 py-1.5 text-sm text-dark-text-primary placeholder:text-dark-text-secondary/40
                         focus:outline-none focus:border-dark-accent-primary"
            />
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2 pt-1">
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium
                         bg-dark-accent-primary hover:bg-dark-accent-hover text-white
                         disabled:opacity-50 transition-colors"
            >
              {isSaving ? (
                <Loader2 size={12} className="animate-spin" />
              ) : saveSuccess ? (
                <Check size={12} />
              ) : null}
              {saveSuccess ? 'Saved' : 'Save'}
            </button>

            <button
              onClick={handleTest}
              disabled={isTesting}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium
                         bg-dark-bg-primary border border-dark-border text-dark-text-secondary
                         hover:text-dark-text-primary hover:border-dark-accent-primary
                         disabled:opacity-50 transition-colors"
            >
              {isTesting ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <RefreshCw size={12} />
              )}
              Test
            </button>

            {testResult !== null && (
              <span className={`flex items-center gap-1 text-xs ${
                testResult ? 'text-green-400' : 'text-red-400'
              }`}>
                {testResult ? <Check size={12} /> : <X size={12} />}
                {testResult ? 'Connected' : 'Failed'}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
