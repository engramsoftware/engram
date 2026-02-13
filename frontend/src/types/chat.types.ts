/**
 * TypeScript types for chat-related data structures.
 */

export interface User {
  id: string
  email: string
  name: string
  createdAt: string
  preferences: {
    theme: string
    defaultProvider?: string
    defaultModel?: string
  }
}

export interface Conversation {
  id: string
  userId: string
  title: string
  createdAt: string
  updatedAt: string
  modelProvider?: string
  modelName?: string
  isPinned: boolean
  messageCount: number
}

export interface ImageAttachment {
  url: string
  filename: string
  content_type: string
}

export interface WebSource {
  title: string
  url: string
  description: string
  age?: string
}

export interface NotificationSummary {
  subject: string
  status: 'sent' | 'scheduled' | 'failed'
  scheduled_at: string | null
}

export interface ContextMetadata {
  memories?: string[]
  notes?: number
  graph?: string
  web_search?: boolean
  warnings?: number
  continuity?: boolean
  search_results?: number
}

export interface Message {
  id: string
  conversationId: string
  role: 'user' | 'assistant' | 'system'
  content: string
  images?: ImageAttachment[]
  web_sources?: WebSource[]
  notifications?: NotificationSummary[]
  context_metadata?: ContextMetadata
  timestamp: string
  metadata: Record<string, unknown>
}

export interface ModelInfo {
  id: string
  name: string
  contextLength?: number
  supportsStreaming: boolean
  supportsFunctions: boolean
  supportsVision: boolean
}

export interface ProviderConfig {
  enabled: boolean
  api_key_set: boolean
  api_key_masked?: string
  base_url?: string
  default_model?: string
  available_models: string[]
}

export interface BraveSearchConfig {
  enabled: boolean
  api_key_set: boolean
  api_key_masked?: string
}

export interface EmailConfig {
  enabled: boolean
  smtp_host: string
  smtp_port: number
  username?: string
  password_set: boolean
  password_masked?: string
  recipient?: string
  from_name: string
}

export interface Neo4jConfig {
  enabled: boolean
  uri?: string
  username?: string
  password_set: boolean
  password_masked?: string
  database: string
}

export interface OptimizationConfig {
  response_validation: boolean
  history_limit: number
}

export interface LLMSettings {
  providers: Record<string, ProviderConfig>
  default_provider?: string
  default_model?: string
  available_providers: string[]
  brave_search?: BraveSearchConfig
  neo4j?: Neo4jConfig
  email?: EmailConfig
  optimization?: OptimizationConfig
}
