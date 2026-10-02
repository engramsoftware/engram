/**
 * Settings > Models: which AI answers, with which model, at what cost.
 *
 * - "In use" card: the provider new chats use and its default model
 * - Provider list: one radio per provider (one is in use at a time)
 * - Cost & accuracy: response validation and the history limit
 */

import { useEffect, useRef, useState } from 'react'
import { Cloud, Monitor, RefreshCw } from 'lucide-react'
import { settingsApi } from '../../services/api'
import { friendlyModelName } from '../../utils/modelNames'
import { newChatProvider, providerMeta } from '../../utils/providers'
import type { LLMSettings } from '../../types/chat.types'
import ProviderSettings from './ProviderSettings'
import OptimizationSettings from './OptimizationSettings'
import { ActionStatus, SelectField, StatusPill, useAction } from './primitives'

interface Props {
  settings: LLMSettings
  onUpdate: () => void
}

export default function ModelsSection({ settings, onUpdate }: Props) {
  const inUse = newChatProvider(settings)
  const [pending, setPending] = useState<string | null>(null)
  // A pick that waits for a key ("pending") is dropped once any other switch succeeds,
  // unless it was made after that switch started (a slow earlier request must not clear it)
  const pendingSeq = useRef(0)
  const changePending = (p: string, on: boolean) => {
    pendingSeq.current++
    setPending(cur => (on ? p : cur === p ? null : cur))
  }
  const activationStart = () => pendingSeq.current
  const activated = (token: number) => { if (pendingSeq.current === token) setPending(null) }
  const providers = settings.available_providers
  const cloud = providers.filter(p => providerMeta(p).needsApiKey)
  const local = providers.filter(p => !providerMeta(p).needsApiKey)

  const group = (label: string, icon: React.ReactNode, list: string[]) => list.length > 0 && (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-dark-text-secondary">
        {icon}
        <span className="text-[10px] font-semibold uppercase tracking-wider">{label}</span>
      </div>
      {list.map(p => (
        <ProviderSettings
          key={p}
          provider={p}
          config={settings.providers[p]}
          settings={settings}
          inUse={p === inUse}
          pending={p === pending}
          onPendingChange={(on) => changePending(p, on)}
          onActivationStart={activationStart}
          onActivated={activated}
          onUpdate={onUpdate}
        />
      ))}
    </div>
  )

  return (
    <div className="space-y-6">
      {inUse
        ? <InUseCard provider={inUse} settings={settings} onUpdate={onUpdate} />
        : (
          <p className="text-xs text-dark-text-secondary">
            To start chatting, pick a provider below. <strong className="text-dark-text-primary">Cloud</strong> providers
            (OpenAI, Anthropic) need an API key; <strong className="text-dark-text-primary">on this computer</strong> means
            LM Studio or Ollama running on the machine.
          </p>
        )}

      <fieldset className="space-y-4">
        <legend className="text-sm font-medium text-dark-text-primary mb-2">Provider</legend>
        {group('Cloud (API key)', <Cloud size={12} />, cloud)}
        {group('On this computer', <Monitor size={12} />, local)}
      </fieldset>

      <section aria-labelledby="cost-accuracy-heading" className="space-y-2">
        <h3 id="cost-accuracy-heading" className="text-sm font-medium text-dark-text-primary">Cost &amp; accuracy</h3>
        <OptimizationSettings config={settings.optimization} onUpdate={onUpdate} />
      </section>
    </div>
  )
}

/** The provider new chats use, and a picker for its default model. */
function InUseCard({ provider, settings, onUpdate }: { provider: string; settings: LLMSettings; onUpdate: () => void }) {
  const meta = providerMeta(provider)
  const config = settings.providers[provider]
  const saved = config?.available_models || []
  const [models, setModels] = useState<string[]>(saved)
  const savedKey = saved.join('\n')
  useEffect(() => { setModels(savedKey ? savedKey.split('\n') : []) }, [savedKey])
  const [state, run] = useAction()

  const current = settings.default_provider === provider ? settings.default_model || '' : ''
  const value = current || models[0] || ''
  // Keep the current default selectable even if the provider no longer lists it
  const list = current && !models.includes(current) ? [current, ...models] : models
  // Repeated friendly names get the raw ID so they can be told apart
  const counts = new Map<string, number>()
  for (const m of list) counts.set(friendlyModelName(m), (counts.get(friendlyModelName(m)) ?? 0) + 1)
  const label = (m: string) => (counts.get(friendlyModelName(m))! > 1 ? `${friendlyModelName(m)} (${m})` : friendlyModelName(m))

  const pick = (model: string) => run(async () => {
    await settingsApi.updateLLMSettings({ default_provider: provider, default_model: model })
    onUpdate()
  }, `New chats use ${friendlyModelName(model)}`)

  const refresh = () => run(async () => {
    const data = await settingsApi.getModels(provider)
    setModels(data.map((m: { id: string }) => m.id))
  }, 'Model list refreshed', "Couldn't load models")

  const needsKey = meta.needsApiKey && !config?.api_key_set

  return (
    <div className="rounded-lg border border-dark-accent-primary/40 bg-dark-bg-secondary p-4 space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-dark-text-secondary">New chats use</span>
        <span className="text-sm font-semibold text-dark-text-primary">{meta.name}</span>
        <StatusPill status={needsKey ? 'needs-setup' : 'in-use'} />
      </div>
      {needsKey && (
        <p className="text-xs text-yellow-400 [.light_&]:text-yellow-800">
          {meta.name} has no API key yet. Add one below, or pick another provider.
        </p>
      )}
      <div className="flex items-end gap-2">
        <div className="flex-1 min-w-0">
          {list.length > 0 ? (
            <SelectField
              label="Default model"
              value={value}
              onChange={pick}
              options={list.map(m => ({ value: m, label: label(m) }))}
              disabled={state.status === 'busy'}
              hint="Picking a model in the chat header also changes this."
            />
          ) : (
            <p className="text-xs text-dark-text-secondary">No models yet. Press Refresh, or check {meta.name}'s settings below.</p>
          )}
        </div>
        <button
          type="button"
          onClick={refresh}
          disabled={state.status === 'busy'}
          className={`inline-flex items-center gap-1 px-2 py-1.5 min-h-[40px] sm:min-h-0 rounded text-xs text-dark-accent-text
                      hover:underline disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-dark-accent-primary
                      ${list.length > 0 ? 'mb-6' : ''}`}
        >
          <RefreshCw size={12} className={state.status === 'busy' ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>
      <ActionStatus state={state} />
    </div>
  )
}
