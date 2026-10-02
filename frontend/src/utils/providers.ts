/**
 * LLM provider metadata and helpers shared by Settings, the chat model picker
 * and the setup wizard.
 */

import type { LLMSettings } from '../types/chat.types'

export interface ProviderMeta {
  name: string
  /** Address used when no URL is saved (matches backend config.py defaults). */
  defaultUrl: string
  needsApiKey: boolean
  keyPlaceholder?: string
  /** Where to get an API key */
  keyUrl?: string
}

export const PROVIDER_META: Record<string, ProviderMeta> = {
  openai: {
    name: 'OpenAI',
    defaultUrl: 'https://api.openai.com/v1',
    needsApiKey: true,
    keyPlaceholder: 'sk-...',
    keyUrl: 'https://platform.openai.com/api-keys',
  },
  anthropic: {
    name: 'Anthropic',
    defaultUrl: 'https://api.anthropic.com',
    needsApiKey: true,
    keyPlaceholder: 'sk-ant-...',
    keyUrl: 'https://console.anthropic.com/settings/keys',
  },
  lmstudio: {
    name: 'LM Studio',
    defaultUrl: 'http://host.docker.internal:1234/v1',
    needsApiKey: false,
  },
  ollama: {
    name: 'Ollama',
    defaultUrl: 'http://host.docker.internal:11434',
    needsApiKey: false,
  },
}

export function providerMeta(provider: string): ProviderMeta {
  return PROVIDER_META[provider] ?? { name: provider, defaultUrl: '', needsApiKey: false }
}

export function providerName(provider: string | null | undefined): string {
  return provider ? providerMeta(provider).name : ''
}

/**
 * Which LLM provider new chats use.
 *
 * Mirrors the chat backend (backend/routers/messages.py): the saved default
 * provider wins, then the first enabled provider. A conversation pinned to a
 * provider from the chat header overrides this for that conversation only.
 */
export function newChatProvider(settings: LLMSettings | null | undefined): string | null {
  if (!settings) return null
  if (settings.default_provider) return settings.default_provider
  return settings.available_providers.find(p => settings.providers[p]?.enabled) ?? null
}

/** The model new chats use with that provider ('' when none is known). */
export function newChatModel(settings: LLMSettings | null | undefined): string {
  const provider = newChatProvider(settings)
  if (!settings || !provider) return ''
  return settings.default_model || settings.providers[provider]?.available_models?.[0] || ''
}
