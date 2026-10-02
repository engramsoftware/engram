/**
 * Which LLM provider new chats use.
 *
 * Mirrors the chat backend (backend/routers/messages.py): the saved default
 * provider wins, then the first enabled provider. A conversation pinned to a
 * provider from the chat header overrides this for that conversation only.
 */

import type { LLMSettings } from '../types/chat.types'

export function newChatProvider(settings: LLMSettings | null | undefined): string | null {
  if (!settings) return null
  if (settings.default_provider) return settings.default_provider
  return settings.available_providers.find(p => settings.providers[p]?.enabled) ?? null
}
