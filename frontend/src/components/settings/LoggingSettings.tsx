/**
 * Server log levels (Settings > Data & logs > Diagnostics).
 *
 * A compact table: the default level plus one level per module group. Each
 * change saves at once and takes effect without a restart. These levels are
 * server-wide (they affect everyone) and are not kept across restarts.
 */

import { useState, useEffect } from 'react'
import { Loader2 } from 'lucide-react'
import { settingsApi } from '../../services/api'
import { ActionButton, ConfirmButton, SelectField } from './primitives'

/** Log levels ordered from most to least verbose */
const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const
const LEVEL_OPTIONS = LOG_LEVELS.map(l => ({ value: l, label: l === 'INFO' ? 'INFO (normal)' : l }))

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
  const [error, setError] = useState<string | null>(null)

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
    setError(null)
    try {
      await settingsApi.updateLoggingConfig({ groups: { [groupKey]: level } })
      setConfig(prev => prev ? {
        ...prev,
        groups: { ...prev.groups, [groupKey]: { ...prev.groups[groupKey], level } },
      } : prev)
    } catch (error) {
      console.error('Failed to update log level:', error)
      setError(`Couldn't change the ${config.groups[groupKey]?.name ?? groupKey} log level`)
    } finally {
      setSaving(null)
    }
  }

  /** Update the default (root) level; groups are re-read since they may follow it */
  const handleRootLevel = async (level: string) => {
    if (!config) return
    setSaving('root')
    setError(null)
    try {
      await settingsApi.updateLoggingConfig({ root_level: level })
      setConfig(prev => prev ? { ...prev, root_level: level } : prev)
      await fetchConfig()
    } catch (error) {
      console.error('Failed to update root log level:', error)
      setError("Couldn't change the default log level")
    } finally {
      setSaving(null)
    }
  }

  /** Set the default and every group to one level */
  const handleSetAll = async (level: string) => {
    if (!config) return
    setSaving('all')
    setError(null)
    const groups: Record<string, string> = {}
    for (const key of Object.keys(config.groups ?? {})) {
      groups[key] = level
    }
    try {
      await settingsApi.updateLoggingConfig({ root_level: level, groups })
      await fetchConfig()
    } catch (error) {
      console.error('Failed to set all log levels:', error)
      setError("Couldn't change the log levels")
    } finally {
      setSaving(null)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-6">
        <Loader2 size={16} className="animate-spin text-dark-text-secondary" />
      </div>
    )
  }

  if (!config) {
    return <p className="text-sm text-dark-text-secondary italic py-2">Couldn't load the log levels.</p>
  }

  const row = (key: string, name: string, hint: string, level: string, onChange: (l: string) => void) => (
    <div key={key} className="flex items-center gap-3 px-3 py-2">
      <div className="flex-1 min-w-0">
        <p className="text-sm text-dark-text-primary">{name}</p>
        <p className="text-[11px] text-dark-text-secondary truncate" title={hint}>{hint}</p>
      </div>
      {saving === key && <Loader2 size={12} className="animate-spin text-dark-accent-primary flex-shrink-0" />}
      <div className="w-36 flex-shrink-0">
        <SelectField label={`${name} log level`} hideLabel value={level} onChange={onChange} options={LEVEL_OPTIONS}
                     disabled={saving !== null} />
      </div>
    </div>
  )

  return (
    <div className="space-y-3">
      {error && <p role="alert" className="text-xs text-red-400 [.light_&]:text-red-700">{error}</p>}

      <div className="rounded-lg border border-dark-border/60 divide-y divide-dark-border/40">
        {row('root', 'Default level', "Used by groups that don't set their own", config.root_level, handleRootLevel)}
        {Object.entries(config.groups ?? {}).map(([groupKey, group]) =>
          row(groupKey, group.name, group.modules.join(', '), group.level, (l) => handleGroupLevel(groupKey, l)))}
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <ActionButton onClick={() => handleSetAll('INFO')} disabled={saving !== null}>Reset all to normal (INFO)</ActionButton>
        <ActionButton onClick={() => handleSetAll('ERROR')} disabled={saving !== null}>Errors only</ActionButton>
        <ConfirmButton
          label="Verbose for everything…"
          prompt="Turn on DEBUG logging for the whole server? It affects everyone here and logs much more detail, including message content."
          confirmLabel="Turn on DEBUG"
          onConfirm={() => handleSetAll('DEBUG')}
          disabled={saving !== null}
        />
        {saving === 'all' && <Loader2 size={12} className="animate-spin text-dark-accent-primary" />}
      </div>
    </div>
  )
}
