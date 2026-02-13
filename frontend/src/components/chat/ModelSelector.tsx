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
import { friendlyModelName } from '../../utils/modelNames'
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
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Close dropdown when clicking/tapping outside.
  // Uses 'pointerup' so it doesn't race with button onPointerUp handlers
  // inside the dropdown (pointerdown fires before the button gets the event).
  useEffect(() => {
    function handleClickOutside(e: PointerEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    if (isOpen) {
      document.addEventListener('pointerup', handleClickOutside)
      return () => document.removeEventListener('pointerup', handleClickOutside)
    }
  }, [isOpen])

  // Fetch settings on mount — find the single active provider
  useEffect(() => {
    async function fetchSettings() {
      try {
        const data = await settingsApi.getLLMSettings()
        setSettings(data)
        // Only one provider can be active at a time
        const enabled = data.available_providers.filter(
          (p: string) => data.providers[p]?.enabled
        )
        const provider = enabled[0] || data.default_provider || ''
        setActiveProvider(provider)
        // Use saved default model, or first available for the provider
        const defaultModel = data.default_model
          || data.providers[provider]?.available_models?.[0]
          || ''
        setSelectedModel(defaultModel)
      } catch (error) {
        console.error('Failed to fetch settings:', error)
      }
    }
    fetchSettings()
  }, [])

  // Load conversation's saved model when switching conversations
  useEffect(() => {
    if (!activeConversationId || !settings) return
    
    async function loadConversationModel() {
      try {
        const conv = await conversationsApi.get(activeConversationId!)
        if (conv.model_name) {
          setSelectedModel(conv.model_name)
        }
        if (conv.model_provider) {
          setActiveProvider(conv.model_provider)
        }
      } catch (error) {
        console.error('Failed to load conversation model:', error)
      }
    }
    loadConversationModel()
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
        onClick={() => setIsOpen(!isOpen)}
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
          <div className="p-2 max-h-48 overflow-y-auto">
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
                onPointerUp={async () => {
                  setSelectedModel(model)
                  setIsOpen(false)
                  // Save model choice to conversation and as default
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
                  }
                }}
                className={`w-full text-left px-3 py-2.5 sm:px-2 sm:py-1.5 rounded text-sm
                           ${model === selectedModel 
                             ? 'bg-dark-accent-primary text-white' 
                             : 'hover:bg-dark-border active:bg-dark-border text-dark-text-primary'
                           }`}
              >
                <span>{friendlyModelName(model)}</span>
                {model !== friendlyModelName(model) && (
                  <span className="text-xs opacity-50 ml-1">({model.split('-').slice(-1)[0]})</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
