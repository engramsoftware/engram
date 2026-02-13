/**
 * Shared friendly display names for LLM model IDs.
 *
 * Used by both the chat ModelSelector and the settings ProviderSettings
 * so model names are consistent everywhere in the UI.
 *
 * For models not in this map, friendlyModelName() attempts to generate
 * a readable name from the raw ID (strip dates, capitalize words).
 */

/** Exact-match friendly names for known model IDs */
const MODEL_NAMES: Record<string, string> = {
  // Anthropic — Claude 4.x
  'claude-opus-4-6': 'Claude Opus 4.6',
  'claude-opus-4-5-20251101': 'Claude Opus 4.5',
  'claude-sonnet-4-5-20250929': 'Claude Sonnet 4.5',
  'claude-opus-4-1-20250805': 'Claude Opus 4.1',
  'claude-opus-4-20250514': 'Claude Opus 4',
  'claude-sonnet-4-20250514': 'Claude Sonnet 4',
  'claude-haiku-4-5-20251001': 'Claude Haiku 4.5',
  // Anthropic — Claude 3.x
  'claude-3-7-sonnet-20250219': 'Claude 3.7 Sonnet',
  'claude-3-5-sonnet-20241022': 'Claude 3.5 Sonnet',
  'claude-3-5-haiku-20241022': 'Claude 3.5 Haiku',
  'claude-3-haiku-20240307': 'Claude 3 Haiku',
  'claude-3-opus-20240229': 'Claude 3 Opus',
  'claude-3-sonnet-20240229': 'Claude 3 Sonnet',
  // OpenAI — GPT
  'gpt-4o': 'GPT-4o',
  'gpt-4o-2024-11-20': 'GPT-4o (Nov 2024)',
  'gpt-4o-2024-08-06': 'GPT-4o (Aug 2024)',
  'gpt-4o-mini': 'GPT-4o Mini',
  'gpt-4o-mini-2024-07-18': 'GPT-4o Mini (Jul 2024)',
  'gpt-4-turbo': 'GPT-4 Turbo',
  'gpt-4-turbo-preview': 'GPT-4 Turbo Preview',
  'gpt-4': 'GPT-4',
  'gpt-3.5-turbo': 'GPT-3.5 Turbo',
  // OpenAI — o-series reasoning
  'o1': 'o1',
  'o1-mini': 'o1 Mini',
  'o1-preview': 'o1 Preview',
  'o3': 'o3',
  'o3-mini': 'o3 Mini',
  'o4-mini': 'o4 Mini',
}

/**
 * Convert a raw model ID like 'claude-opus-4-5-20251101' into a readable name.
 *
 * 1. Check the exact-match map first.
 * 2. If not found, strip trailing date stamps (YYYYMMDD) and version suffixes,
 *    then title-case the remaining words.
 *
 * @param modelId - Raw model identifier from the API
 * @returns Human-friendly display name
 */
export function friendlyModelName(modelId: string): string {
  if (MODEL_NAMES[modelId]) return MODEL_NAMES[modelId]

  // Auto-generate: strip trailing date (8 digits) and dashes, title-case
  let cleaned = modelId
    // Remove trailing date like -20250514
    .replace(/-\d{8}$/, '')
    // Remove trailing date with extra segment like -4-5-20251101 → keep -4-5
    .replace(/-(\d{8})$/, '')

  // Title-case each segment: "claude-opus-4-1" → "Claude Opus 4.1"
  const parts = cleaned.split('-')
  const titled = parts.map((p, i) => {
    // Keep version numbers as-is but join consecutive digits with dots
    if (/^\d+$/.test(p) && i > 0 && /^\d+$/.test(parts[i - 1])) {
      return '.' + p
    }
    if (/^\d+$/.test(p)) return p
    return p.charAt(0).toUpperCase() + p.slice(1)
  })

  return titled.join(' ').replace(/ \./g, '.')
}
