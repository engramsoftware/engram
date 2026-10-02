/**
 * Model selector dropdown for choosing LLM provider and model.
 *
 * Shows cached models instantly and refreshes from the API in the background.
 * Displays friendly model names and a loading spinner while fetching.
 */

import { useState, useEffect, useRef } from 'react'
import { ChevronDown, Loader2 } from 'lucide-react'
import { settingsApi, conversationsApi } from '../../services/api'
import { useChatStore } from '../../stores/chatStore'
import { useUIStore } from '../../stores/uiStore'
import { friendlyModelName } from '../../utils/modelNames'
import { newChatProvider } from '../../utils/providers'
import type { LLMSettings } from '../../types/chat.types'

/** Friendly display names for provider keys */
const PROVIDER_NAMES: Record<string, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  lmstudio: 'LM Studio',
  ollama: 'Ollama',
}

export default function ModelSelector() {
  const { activeConversationId } = useChatStore()
  const [settings, setSettings] = useState<LLMSettings | null>(null)
  const [activeProvider, setActiveProvider] = useState<string>('')
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [models, setModels] = useState<string[]>([])
  const [isLoadingModels, setIsLoadingModels] = useState(false)
  const [isOpen, setIsOpen] = useState(false)
  const [pickError, setPickError] = useState('')
  const openSettings = useUIStore(s => s.openSettings)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  // Close on a press outside the dropdown, or on Escape. Options use onClick, and
  // presses inside the dropdown are ignored here, so the two can't race.
  useEffect(() => {
    if (!isOpen) return
    function handlePointerDown(e: PointerEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key !== 'Escape') return
      e.preventDefault() // capture phase: global shortcuts see it as handled
      setIsOpen(false)
      triggerRef.current?.focus()
    }
    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown, true)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown, true)
    }
  }, [isOpen])

  // Fetch settings on mount
  useEffect(() => {
    settingsApi.getLLMSettings()
      .then(setSettings)
      .catch(error => console.error('Failed to fetch settings:', error))
  }, [])

  // Show what this chat will use, resolved like the chat backend: the conversation's
  // own provider/model when it has one, otherwise the new-chat default. Re-run on every
  // conversation switch so one chat's choice doesn't linger on the next.
  useEffect(() => {
    if (!settings) return
    const fallbackProvider = newChatProvider(settings) || ''
    const defaultsFor = (provider: string) => (provider === settings.default_provider && settings.default_model)
      || settings.providers[provider]?.available_models?.[0] || ''
    const showDefaults = () => {
      setActiveProvider(fallbackProvider)
      setSelectedModel(settings.default_model || defaultsFor(fallbackProvider))
    }
    if (!activeConversationId) { showDefaults(); return }

    let cancelled = false
    conversationsApi.get(activeConversationId)
      .then(conv => {
        if (cancelled) return
        // Unknown providers (e.g. "chatgpt-import" on imported chats) can't list models;
        // show the default provider so a pick re-pins the chat to a working one
        if (conv.model_provider && settings.available_providers.includes(conv.model_provider)) {
          setActiveProvider(conv.model_provider)
          setSelectedModel(conv.model_name || defaultsFor(conv.model_provider))
        } else {
          showDefaults()
        }
      })
      .catch(error => {
        console.error('Failed to load conversation model:', error)
        if (!cancelled) showDefaults()
      })
    return () => { cancelled = true }
  }, [activeConversationId, settings])

  // Load models when active provider changes: show cached instantly, refresh in background
  useEffect(() => {
    if (!activeProvider) return

    // Immediately show cached models from settings (no network delay)
    const cached = settings?.providers[activeProvider]?.available_models || []
    if (cached.length > 0) {
      setModels(cached)
    }

    // Background refresh from API
    let cancelled = false
    setIsLoadingModels(true)

    async function refreshModels() {
      try {
        const data = await settingsApi.getModels(activeProvider)
        if (cancelled) return
        const ids = data.map((m: { id: string }) => m.id)
        if (ids.length > 0) setModels(ids)
      } catch (error) {
        console.error('Failed to refresh models:', error)
        // Cached models already shown — no action needed
      } finally {
        if (!cancelled) setIsLoadingModels(false)
      }
    }
    refreshModels()

    return () => { cancelled = true }
  }, [activeProvider, settings])

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        ref={triggerRef}
        onClick={() => { setIsOpen(!isOpen); setPickError('') }}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg
                   bg-dark-bg-secondary hover:bg-dark-border
                   text-dark-text-primary text-sm transition-colors"
      >
        <span className="truncate max-w-[200px]">
          {selectedModel ? friendlyModelName(selectedModel) : 'Select model'}
        </span>
        <ChevronDown size={16} className={`transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div className="absolute top-full left-0 mt-1 w-[calc(100vw-2rem)] sm:w-72 max-w-80
                        bg-dark-bg-secondary border border-dark-border rounded-lg shadow-lg z-50">
          {/* Active provider label */}
          <div className="px-3 py-2 border-b border-dark-border">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-dark-text-secondary">
              {PROVIDER_NAMES[activeProvider] || activeProvider || 'No provider'}
            </span>
          </div>

          {/* Model selection */}
          <div className="p-2 max-h-48 overflow-y-auto" role="listbox" aria-label="Model">
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs text-dark-text-secondary">Model</label>
              {isLoadingModels && (
                <Loader2 size={12} className="animate-spin text-dark-text-secondary" />
              )}
            </div>
            {models.length === 0 && !isLoadingModels && (
              <p className="text-xs text-dark-text-secondary py-2 italic">No models available</p>
            )}
            {models.length === 0 && isLoadingModels && (
              <p className="text-xs text-dark-text-secondary py-2 italic">Loading models...</p>
            )}
            {models.map((model) => (
              <button
                key={model}
                role="option"
                aria-selected={model === selectedModel}
                onClick={async () => {
                  const previous = selectedModel
                  setSelectedModel(model)
                  setIsOpen(false)
                  setPickError('')
                  // Save the choice to this conversation and as the default for new chats
                  try {
                    if (activeConversationId) {
                      await conversationsApi.update(activeConversationId, {
                        model_provider: activeProvider,
                        model_name: model
                      })
                    }
                    await settingsApi.updateLLMSettings({
                      default_provider: activeProvider,
                      default_model: model,
                    })
                  } catch (e) {
                    console.error('Failed to update model:', e)
                    setSelectedModel(previous)
                    setPickError(`Couldn't switch to ${friendlyModelName(model)}. Try again.`)
                  }
                }}
                className={`w-full text-left px-3 py-2.5 sm:px-2 sm:py-1.5 rounded text-sm
                           ${model === selectedModel 
                             ? 'bg-dark-accent-primary text-white' 
                             : 'hover:bg-dark-border active:bg-dark-border text-dark-text-primary'
                           }`}
              >
                <span>{friendlyModelName(model)}</span>
                {/* Only when two models share a friendly name: show the raw ID to tell them apart */}
                {models.filter(m => friendlyModelName(m) === friendlyModelName(model)).length > 1 && (
                  <span className="text-xs opacity-60 ml-1">({model})</span>
                )}
              </button>
            ))}
          </div>

          <div className="px-3 py-2 border-t border-dark-border flex items-center justify-between gap-2">
            <span className="text-[11px] text-dark-text-secondary">Also used for new chats</span>
            <button
              type="button"
              onClick={() => { setIsOpen(false); openSettings('models') }}
              className="text-xs text-dark-accent-primary hover:underline focus:outline-none focus-visible:underline"
            >
              Manage models…
            </button>
          </div>
        </div>
      )}
      {pickError && (
        <p role="alert" className="absolute top-full left-0 mt-1 w-max max-w-[18rem] px-2 py-1 rounded bg-dark-bg-secondary
                                   border border-red-500/40 text-xs text-red-400 [.light_&]:text-red-700 z-50">
          {pickError}
        </p>
      )}
    </div>
  )
}
