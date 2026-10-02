/**
 * Settings > Add-ins: the one place to turn add-ins on or off, read what
 * they do, change their settings and uninstall them. (This replaces the
 * separate Add-ins page; its sidebar link now opens this section.)
 */

import { useEffect, useMemo, useState } from 'react'
import { Package } from 'lucide-react'
import { addinsApi } from '../../services/api'
import { useAddinsStore } from '../../stores/addinsStore'
import type { Addin, AddinType } from '../../types/addin.types'
import AddinSettingsRenderer from './AddinSettingsRenderer'
import { ActionButton, Badge, ConfirmButton, Disclosure, ErrorStatus, SettingsCard, useAction } from './primitives'

/** What each add-in type is, in plain words. */
export const ADDIN_TYPE_LABELS: Record<AddinType, string> = {
  tool: 'AI tool',
  gui: 'Sidebar panel',
  interceptor: 'Message filter',
  hybrid: 'Multi-part',
}

const HOW_IT_WORKS: Record<AddinType, string> = {
  tool: 'Adds tools the AI can call during a conversation when they are relevant.',
  gui: 'Adds a panel to the sidebar that you use directly.',
  interceptor: 'Works on messages: it can change what you send before the AI sees it, and the reply before you see it.',
  hybrid: 'Combines several of these: AI tools, a sidebar panel and message filters.',
}

/** Permission IDs used in add-in manifests, in plain words. */
const PERMISSION_LABELS: Record<string, string> = {
  network: 'uses the internet',
  storage: 'stores files',
  memory: 'uses your memories',
  graph: 'uses the knowledge graph',
  search: 'searches',
  'llm.messages': 'sees chat messages',
  read_messages: 'reads messages',
  write_context: 'adds context to replies',
  local_llm: 'uses a local AI model',
}

const permissionLabel = (p: string) => PERMISSION_LABELS[p] ?? p.replace(/[._]/g, ' ')

/** Manifest keys that only matter to the app itself */
const HIDDEN_CONFIG_KEYS = new Set(['icon', 'label', 'mountPoints'])

/** Manifest keys whose values are secrets */
const SECRET_KEY = /key|password|secret|token/i

function formatConfigValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (SECRET_KEY.test(key)) return 'set (hidden)'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

type Filter = 'all' | 'on' | 'off'

export default function AddinsSection({ active }: { active: boolean }) {
  const { addins, loaded, error, fetchAddins } = useAddinsStore()
  const [filter, setFilter] = useState<Filter>('all')

  // Re-read every time the section is opened (this also re-seeds missing built-ins)
  useEffect(() => { if (active) fetchAddins() }, [active, fetchAddins])

  const sorted = useMemo(() => [...addins].sort((a, b) =>
    a.enabled !== b.enabled ? (a.enabled ? -1 : 1) : a.name.localeCompare(b.name)), [addins])
  const shown = sorted.filter(a => filter === 'all' || (filter === 'on') === a.enabled)

  if (error && addins.length === 0) {
    return (
      <div role="alert" className="flex items-center gap-3 text-xs text-red-400 [.light_&]:text-red-700">
        Couldn't load add-ins.
        <ActionButton onClick={fetchAddins}>Retry</ActionButton>
      </div>
    )
  }
  if (!loaded) return <p className="text-xs text-dark-text-secondary py-2">Loading add-ins…</p>
  if (addins.length === 0) {
    return <p className="text-xs text-dark-text-secondary py-2">No add-ins yet. Built-in add-ins appear here automatically.</p>
  }

  return (
    <div className="space-y-3">
      <div role="group" aria-label="Show" className="inline-flex rounded-md border border-dark-border overflow-hidden">
        {(['all', 'on', 'off'] as const).map(f => (
          <button
            key={f}
            type="button"
            aria-pressed={filter === f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 min-h-[40px] sm:min-h-0 text-xs transition-colors focus:outline-none focus-visible:ring-2
                        focus-visible:ring-inset focus-visible:ring-dark-accent-primary ${
              filter === f ? 'bg-dark-bg-secondary text-dark-text-primary font-medium' : 'text-dark-text-secondary hover:text-dark-text-primary'
            }`}
          >
            {f === 'all' ? 'All' : f === 'on' ? 'On' : 'Off'}
          </button>
        ))}
      </div>

      {error && (
        <div role="alert" className="flex items-center gap-3 text-xs text-red-400 [.light_&]:text-red-700">
          Couldn't refresh the add-ins list; it may be out of date.
          <ActionButton onClick={fetchAddins}>Retry</ActionButton>
        </div>
      )}

      {/* Filtered-out cards are hidden, not removed, so their unsaved settings survive */}
      <div className="space-y-2">
        {sorted.map(addin => (
          <div key={addin.id} hidden={!shown.includes(addin)}>
            <AddinCard addin={addin} onChanged={fetchAddins} />
          </div>
        ))}
        {shown.length === 0 && (
          <p className="text-xs text-dark-text-secondary py-2">No add-ins are {filter === 'on' ? 'on' : 'off'}.</p>
        )}
      </div>
    </div>
  )
}

function AddinCard({ addin, onChanged }: { addin: Addin; onChanged: () => Promise<void> }) {
  // Settings load on first open and then stay mounted, so drafts survive collapsing
  const [opened, setOpened] = useState(false)
  const [toggleState, runToggle] = useAction()
  const [uninstallState, runUninstall] = useAction()
  const configEntries = Object.entries(addin.config?.settings || {}).filter(([k]) => !HIDDEN_CONFIG_KEYS.has(k))

  const toggle = () => runToggle(async () => {
    await addinsApi.toggle(addin.id)
    await onChanged()
  }, `${addin.name} turned ${addin.enabled ? 'off' : 'on'}`, `Couldn't change ${addin.name}`)

  const uninstall = () => runUninstall(async () => {
    await addinsApi.uninstall(addin.id)
    await onChanged()
  }, `${addin.name} uninstalled`, `Couldn't uninstall ${addin.name}`)

  return (
    <SettingsCard
      title={addin.name}
      subtitle={addin.description}
      status={addin.enabled ? 'on' : 'off'}
      badges={<Badge>{ADDIN_TYPE_LABELS[addin.addin_type] ?? addin.addin_type}</Badge>}
      aside={toggleState.status === 'error' ? <ErrorStatus state={toggleState} /> : undefined}
      enabled={addin.enabled}
      keepMounted
      onOpenChange={(o) => { if (o) setOpened(true) }}
      onToggle={toggle}
      toggleLabel={addin.name}
      toggleDisabled={toggleState.status === 'busy'}
    >
      {addin.description && <p className="text-xs text-dark-text-primary/90 leading-relaxed">{addin.description}</p>}
      <p className="text-xs text-dark-text-secondary leading-relaxed">
        <span className="font-medium text-dark-text-primary">How it works: </span>
        {HOW_IT_WORKS[addin.addin_type] ?? ''}
      </p>
      {addin.permissions.length > 0 && (
        <p className="text-xs text-dark-text-secondary">
          <span className="font-medium text-dark-text-primary">Can: </span>
          {addin.permissions.map(permissionLabel).join(' · ')}
        </p>
      )}
      <p className="flex items-center gap-2 text-[11px] text-dark-text-secondary">
        {addin.built_in && <span className="inline-flex items-center gap-1"><Package size={11} /> Built-in</span>}
        <span>Version {addin.version}</span>
      </p>

      <div className="pt-1">
        <h4 className="text-[10px] font-semibold uppercase tracking-wider text-dark-text-secondary mb-2">Settings</h4>
        {opened && <AddinSettingsRenderer addinName={addin.internal_name} disabled={!addin.enabled} />}
      </div>

      {configEntries.length > 0 && (
        <Disclosure summary="Technical details">
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
            {configEntries.map(([key, val]) => (
              <div key={key} className="flex items-center justify-between gap-2 bg-dark-bg-primary rounded px-3 py-1.5 min-w-0">
                <dt className="text-xs text-dark-text-secondary">{key.replace(/_/g, ' ')}</dt>
                <dd className="text-xs text-dark-text-primary font-mono truncate" title={formatConfigValue(key, val)}>{formatConfigValue(key, val)}</dd>
              </div>
            ))}
          </dl>
        </Disclosure>
      )}

      {!addin.built_in && (
        <div className="flex items-center gap-2 flex-wrap pt-1">
          <ConfirmButton
            label="Uninstall"
            prompt={`Uninstall ${addin.name}? Its settings are removed too.`}
            confirmLabel="Uninstall"
            danger
            busy={uninstallState.status === 'busy'}
            onConfirm={uninstall}
          />
          <ErrorStatus state={uninstallState} />
        </div>
      )}
    </SettingsCard>
  )
}
