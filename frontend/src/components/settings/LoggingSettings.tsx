/**
 * Logging configuration panel.
 *
 * Allows toggling log levels per module group (pipeline, memory, graph, etc.)
 * and the root logger. Changes take effect immediately — no restart needed.
 */

import { useState, useEffect } from 'react'
import { Loader2 } from 'lucide-react'
import { settingsApi } from '../../services/api'

/** Log levels ordered from most to least verbose */
const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const

/** Color coding for log level badges */
const LEVEL_COLORS: Record<string, string> = {
  DEBUG: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  INFO: 'bg-green-500/20 text-green-400 border-green-500/30',
  WARNING: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  ERROR: 'bg-red-500/20 text-red-400 border-red-500/30',
  CRITICAL: 'bg-red-700/20 text-red-300 border-red-700/30',
}

interface LogGroup {
  name: string
  level: string
  modules: string[]
}

interface LoggingConfig {
  root_level: string
  groups: Record<string, LogGroup>
}

export default function LoggingSettings() {
  const [config, setConfig] = useState<LoggingConfig | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [saving, setSaving] = useState<string | null>(null)

  const fetchConfig = async () => {
    try {
      const data = await settingsApi.getLoggingConfig()
      setConfig(data)
    } catch (error) {
      console.error('Failed to fetch logging config:', error)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => { fetchConfig() }, [])

  /** Update a single group's level and save immediately */
  const handleGroupLevel = async (groupKey: string, level: string) => {
    if (!config) return
    setSaving(groupKey)
    try {
      await settingsApi.updateLoggingConfig({ groups: { [groupKey]: level } })
      // Update local state optimistically
      setConfig(prev => prev ? {
        ...prev,
        groups: {
          ...prev.groups,
          [groupKey]: { ...prev.groups[groupKey], level },
        },
      } : prev)
    } catch (error) {
      console.error('Failed to update log level:', error)
    } finally {
      setSaving(null)
    }
  }

  /** Update the root log level */
  const handleRootLevel = async (level: string) => {
    if (!config) return
    setSaving('root')
    try {
      await settingsApi.updateLoggingConfig({ root_level: level })
      setConfig(prev => prev ? { ...prev, root_level: level } : prev)
    } catch (error) {
      console.error('Failed to update root log level:', error)
    } finally {
      setSaving(null)
    }
  }

  /** Set all groups to a specific level at once */
  const handleSetAll = async (level: string) => {
    if (!config) return
    setSaving('all')
    const groups: Record<string, string> = {}
    for (const key of Object.keys(config.groups)) {
      groups[key] = level
    }
    try {
      await settingsApi.updateLoggingConfig({ root_level: level, groups })
      await fetchConfig()
    } catch (error) {
      console.error('Failed to set all log levels:', error)
    } finally {
      setSaving(null)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 size={16} className="animate-spin text-dark-text-secondary" />
      </div>
    )
  }

  if (!config) {
    return (
      <p className="text-sm text-dark-text-secondary italic py-4">
        Failed to load logging configuration
      </p>
    )
  }

  return (
    <div className="space-y-4">
      {/* Root level + quick actions */}
      <div className="rounded-lg border border-dark-border bg-dark-bg-secondary p-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="text-sm font-medium text-dark-text-primary">Root Log Level</h3>
            <p className="text-xs text-dark-text-secondary mt-0.5">
              Default level for all modules without a specific override
            </p>
          </div>
          {saving === 'root' && <Loader2 size={14} className="animate-spin text-dark-accent-primary" />}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {LOG_LEVELS.map(level => (
            <button
              key={level}
              onClick={() => handleRootLevel(level)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium border transition-all ${
                config.root_level === level
                  ? LEVEL_COLORS[level]
                  : 'bg-dark-bg-primary border-dark-border/50 text-dark-text-secondary hover:border-dark-border hover:text-dark-text-primary'
              }`}
            >
              {level}
            </button>
          ))}
        </div>

        {/* Quick actions */}
        <div className="flex gap-2 mt-3 pt-3 border-t border-dark-border/30">
          <button
            onClick={() => handleSetAll('DEBUG')}
            disabled={saving === 'all'}
            className="text-[11px] text-dark-text-secondary hover:text-blue-400 transition-colors"
          >
            Enable all DEBUG
          </button>
          <span className="text-dark-border">·</span>
          <button
            onClick={() => handleSetAll('INFO')}
            disabled={saving === 'all'}
            className="text-[11px] text-dark-text-secondary hover:text-green-400 transition-colors"
          >
            Reset all to INFO
          </button>
          <span className="text-dark-border">·</span>
          <button
            onClick={() => handleSetAll('ERROR')}
            disabled={saving === 'all'}
            className="text-[11px] text-dark-text-secondary hover:text-red-400 transition-colors"
          >
            Errors only
          </button>
          {saving === 'all' && <Loader2 size={12} className="animate-spin text-dark-accent-primary ml-1" />}
        </div>
      </div>

      {/* Per-group controls */}
      {Object.entries(config.groups).map(([groupKey, group]) => (
        <div
          key={groupKey}
          className="rounded-lg border border-dark-border/50 bg-dark-bg-secondary/50 px-4 py-3"
        >
          <div className="flex items-center justify-between mb-2">
            <div className="flex-1 min-w-0">
              <h3 className="text-sm font-medium text-dark-text-primary">{group.name}</h3>
              <p className="text-[10px] text-dark-text-secondary/60 truncate mt-0.5">
                {group.modules.join(', ')}
              </p>
            </div>
            {saving === groupKey && (
              <Loader2 size={12} className="animate-spin text-dark-accent-primary flex-shrink-0 ml-2" />
            )}
          </div>
          <div className="flex flex-wrap gap-1">
            {LOG_LEVELS.map(level => (
              <button
                key={level}
                onClick={() => handleGroupLevel(groupKey, level)}
                className={`px-2.5 py-1 rounded text-[11px] font-medium border transition-all ${
                  group.level === level
                    ? LEVEL_COLORS[level]
                    : 'bg-dark-bg-primary/50 border-transparent text-dark-text-secondary/50 hover:border-dark-border/50 hover:text-dark-text-secondary'
                }`}
              >
                {level}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
