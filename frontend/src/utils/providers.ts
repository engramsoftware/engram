/**
 * LLM provider metadata and helpers shared by Settings, the chat model picker
 * and the setup wizard.
 */

import type { LLMSettings } from '../types/chat.types'

export interface ProviderMeta {
  name: string
  /** Address used when no URL is saved (matches backend/llm/registry.py). Empty = the user must give one. */
  defaultUrl: string
  /** Chat can't work without a key */
  needsApiKey: boolean
  /** The server may take a key (required or optional) */
  acceptsApiKey: boolean
  /** No default address: a URL has to be entered (Custom) */
  requiresUrl: boolean
  /** Runs on this computer: no account, no per-token cost */
  local: boolean
  keyPlaceholder?: string
  /** Where to get an API key */
  keyUrl?: string
  /** Example address shown where there is no default */
  urlExample?: string
  /** One-line pitch (setup wizard) */
  blurb: string
  /** Cost label (setup wizard) */
  cost: string
}

/**
 * Every provider, in display order.
 *
 * Mirrors backend/llm/registry.py (the source of truth);
 * backend/tests/test_llm_registry.py fails if the two disagree.
 */
export const PROVIDER_META: Record<string, ProviderMeta> = {
  lmstudio: {
    name: 'LM Studio',
    defaultUrl: 'http://host.docker.internal:1234/v1',
    needsApiKey: false,
    acceptsApiKey: false,
    requiresUrl: false,
    local: true,
    blurb: 'Run AI models locally on your PC. Free, private, no internet needed.',
    cost: 'Free (local)',
  },
  ollama: {
    name: 'Ollama',
    defaultUrl: 'http://host.docker.internal:11434',
    needsApiKey: false,
    acceptsApiKey: false,
    requiresUrl: false,
    local: true,
    blurb: 'Another great local option. Lightweight and easy to set up.',
    cost: 'Free (local)',
  },
  openai: {
    name: 'OpenAI',
    defaultUrl: 'https://api.openai.com/v1',
    needsApiKey: true,
    acceptsApiKey: true,
    requiresUrl: false,
    local: false,
    keyPlaceholder: 'sk-...',
    keyUrl: 'https://platform.openai.com/api-keys',
    blurb: 'GPT-4o and GPT-4o-mini. Best overall quality. Pay per use.',
    cost: 'Pay per token',
  },
  anthropic: {
    name: 'Anthropic',
    defaultUrl: 'https://api.anthropic.com',
    needsApiKey: true,
    acceptsApiKey: true,
    requiresUrl: false,
    local: false,
    keyPlaceholder: 'sk-ant-...',
    keyUrl: 'https://console.anthropic.com/settings/keys',
    blurb: 'Claude Sonnet and Haiku. Excellent for long conversations.',
    cost: 'Pay per token',
  },
  custom: {
    name: 'Custom (OpenAI-compatible)',
    defaultUrl: '',
    needsApiKey: false,
    acceptsApiKey: true,
    requiresUrl: true,
    local: false,
    keyPlaceholder: 'Only if the server asks for one',
    urlExample: 'http://localhost:8080/v1',
    blurb: 'Any server that speaks the OpenAI API: llama.cpp, vLLM, Groq, Together, OpenRouter.',
    cost: 'Depends on the server',
  },
}

/** Ids in display order (the backend's registry order). */
export const PROVIDER_IDS = Object.keys(PROVIDER_META)

/** Whether a provider is usable once it has what it needs (key and/or URL). */
export function providerReady(provider: string, saved: { api_key_set?: boolean; base_url?: string | null } | undefined): boolean {
  const meta = providerMeta(provider)
  return (!meta.needsApiKey || !!saved?.api_key_set) && (!meta.requiresUrl || !!saved?.base_url)
}

export function providerMeta(provider: string): ProviderMeta {
  return PROVIDER_META[provider] ?? {
    name: provider, defaultUrl: '', needsApiKey: false, acceptsApiKey: false, requiresUrl: false,
    local: false, blurb: '', cost: '',
  }
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
