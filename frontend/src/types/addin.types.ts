/**
 * TypeScript types for add-in/plugin system.
 */

export type AddinType = 'tool' | 'gui' | 'interceptor' | 'hybrid'

export interface Addin {
  id: string
  name: string
  internal_name: string  // Manifest ID for routing (e.g. 'skill_voyager')
  description?: string
  addin_type: AddinType
  enabled: boolean
  config: {
    settings: Record<string, unknown>
  }
  installed_at: string
  version: string
  permissions: string[]
  built_in?: boolean
}

export interface Persona {
  id: string
  name: string
  description?: string
  system_prompt: string
  is_default: boolean
  created_at: string
  updated_at: string
}

export interface Memory {
  id: string
  content: string
  category: string
  tags: string[]
  enabled: boolean
  created_at: string
  updated_at: string
  source: 'manual' | 'autonomous'
  memory_type: string
  confidence: number
}

export interface SearchResult {
  id: string
  conversationId: string
  conversationTitle?: string
  content: string
  role: string
  timestamp: string
  score: number
  highlight?: string
}
