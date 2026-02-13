/**
 * API service for backend communication.
 * Handles HTTP requests with authentication.
 */

import { useAuthStore } from '../stores/authStore'

const API_BASE = '/api'

// Get auth token from store
function getAuthHeader(): Record<string, string> {
  const token = useAuthStore.getState().token
  return token ? { Authorization: `Bearer ${token}` } : {}
}

// Generic fetch wrapper with auth
async function fetchWithAuth(
  endpoint: string,
  options: RequestInit = {}
): Promise<Response> {
  const headers = {
    'Content-Type': 'application/json',
    ...getAuthHeader(),
    ...options.headers,
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  })

  // Handle 401 by logging out
  if (response.status === 401) {
    useAuthStore.getState().logout()
  }

  return response
}

// ============================================================
// Auth API
// ============================================================
export const authApi = {
  async login(email: string, password: string) {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    if (!res.ok) throw new Error((await res.json()).detail || 'Login failed')
    return res.json()
  },

  async register(email: string, name: string, password: string) {
    const res = await fetch(`${API_BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, name, password }),
    })
    if (!res.ok) throw new Error((await res.json()).detail || 'Registration failed')
    return res.json()
  },

  async getMe() {
    const res = await fetchWithAuth('/auth/me')
    if (!res.ok) throw new Error('Failed to get user')
    return res.json()
  },

  async resetPassword(email: string, newPassword: string) {
    const res = await fetch(`${API_BASE}/auth/reset-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, new_password: newPassword }),
    })
    if (!res.ok) throw new Error((await res.json()).detail || 'Reset failed')
    return res.json()
  },
}

// ============================================================
// Conversations API
// ============================================================
export const conversationsApi = {
  async list() {
    const res = await fetchWithAuth('/conversations')
    if (!res.ok) throw new Error('Failed to fetch conversations')
    return res.json()
  },

  async create(title?: string, modelProvider?: string, modelName?: string) {
    const res = await fetchWithAuth('/conversations', {
      method: 'POST',
      body: JSON.stringify({ title, model_provider: modelProvider, model_name: modelName }),
    })
    if (!res.ok) throw new Error('Failed to create conversation')
    return res.json()
  },

  async get(id: string) {
    const res = await fetchWithAuth(`/conversations/${id}`)
    if (!res.ok) throw new Error('Failed to fetch conversation')
    return res.json()
  },

  async update(id: string, data: { title?: string; isPinned?: boolean; model_provider?: string; model_name?: string }) {
    const res = await fetchWithAuth(`/conversations/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
    if (!res.ok) throw new Error('Failed to update conversation')
    return res.json()
  },

  async delete(id: string) {
    const res = await fetchWithAuth(`/conversations/${id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error('Failed to delete conversation')
    return res.json()
  },
}

// ============================================================
// Messages API
// ============================================================
export const messagesApi = {
  async list(conversationId: string) {
    const res = await fetchWithAuth(`/messages/${conversationId}`)
    if (!res.ok) throw new Error('Failed to fetch messages')
    return res.json()
  },

  /**
   * Send a message via POST and return the fetch Response for SSE streaming.
   * The caller should read response.body as a ReadableStream.
   */
  async sendMessage(
    conversationId: string,
    content: string,
    images?: { url: string; filename: string; content_type: string }[],
  ): Promise<Response> {
    const payload: Record<string, unknown> = { conversation_id: conversationId, content }
    if (images && images.length > 0) payload.images = images
    const response = await fetchWithAuth('/messages', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}))
      throw new Error(errorData.detail || `HTTP ${response.status}`)
    }
    return response
  },
}

// ============================================================
// Settings API
// ============================================================
export const settingsApi = {
  async getLLMSettings() {
    const res = await fetchWithAuth('/settings/llm')
    if (!res.ok) throw new Error('Failed to fetch settings')
    return res.json()
  },

  async updateLLMSettings(settings: Record<string, unknown>) {
    const res = await fetchWithAuth('/settings/llm', {
      method: 'PUT',
      body: JSON.stringify(settings),
    })
    if (!res.ok) throw new Error('Failed to update settings')
    return res.json()
  },

  async testConnection(provider: string, apiKey?: string, baseUrl?: string) {
    const params = new URLSearchParams({ provider_name: provider })
    if (apiKey) params.append('api_key', apiKey)
    if (baseUrl) params.append('base_url', baseUrl)
    
    const res = await fetchWithAuth(`/settings/test-connection?${params}`, {
      method: 'POST',
    })
    return res.json()
  },

  async getModels(provider: string) {
    const res = await fetchWithAuth(`/settings/models/${provider}`)
    if (!res.ok) throw new Error('Failed to fetch models')
    return res.json()
  },

  async testBraveSearch(apiKey?: string) {
    const params = new URLSearchParams()
    if (apiKey) params.append('api_key', apiKey)
    const res = await fetchWithAuth(`/settings/test-brave-search?${params}`, {
      method: 'POST',
    })
    return res.json()
  },

  async testEmail() {
    const res = await fetchWithAuth('/settings/test-email', { method: 'POST' })
    return res.json()
  },

  async testNeo4j(uri?: string, username?: string, password?: string, database?: string) {
    const params = new URLSearchParams()
    if (uri) params.append('uri', uri)
    if (username) params.append('username', username)
    if (password) params.append('password', password)
    if (database) params.append('database', database)
    const res = await fetchWithAuth(`/settings/test-neo4j?${params}`, {
      method: 'POST',
    })
    return res.json()
  },

  async getLoggingConfig() {
    const res = await fetchWithAuth('/settings/logging')
    if (!res.ok) throw new Error('Failed to fetch logging config')
    return res.json()
  },

  async updateLoggingConfig(config: { root_level?: string; groups?: Record<string, string> }) {
    const res = await fetchWithAuth('/settings/logging', {
      method: 'PUT',
      body: JSON.stringify(config),
    })
    if (!res.ok) throw new Error('Failed to update logging config')
    return res.json()
  },

  async getRecentLogs(params?: { limit?: number; level?: string; search?: string; logger_name?: string }) {
    const qs = new URLSearchParams()
    if (params?.limit) qs.append('limit', String(params.limit))
    if (params?.level) qs.append('level', params.level)
    if (params?.search) qs.append('search', params.search)
    if (params?.logger_name) qs.append('logger_name', params.logger_name)
    const res = await fetchWithAuth(`/settings/logs?${qs}`)
    if (!res.ok) throw new Error('Failed to fetch logs')
    return res.json()
  },
}

// ============================================================
// Knowledge Graph API
// ============================================================
export const graphApi = {
  async getStats() {
    const res = await fetchWithAuth('/graph/stats')
    if (!res.ok) throw new Error('Failed to fetch graph stats')
    return res.json()
  },

  async listNodes(params?: { search?: string; node_type?: string; limit?: number; offset?: number }) {
    const qs = new URLSearchParams()
    if (params?.search) qs.append('search', params.search)
    if (params?.node_type) qs.append('node_type', params.node_type)
    if (params?.limit) qs.append('limit', String(params.limit))
    if (params?.offset) qs.append('offset', String(params.offset))
    const res = await fetchWithAuth(`/graph/nodes?${qs}`)
    if (!res.ok) throw new Error('Failed to fetch graph nodes')
    return res.json()
  },

  async getNeighborhood(nodeName: string, depth = 1) {
    const res = await fetchWithAuth(`/graph/nodes/${encodeURIComponent(nodeName)}/neighborhood?depth=${depth}`)
    if (!res.ok) throw new Error('Failed to fetch node neighborhood')
    return res.json()
  },

  async deleteNode(nodeName: string) {
    const res = await fetchWithAuth(`/graph/nodes/${encodeURIComponent(nodeName)}`, { method: 'DELETE' })
    if (!res.ok) throw new Error('Failed to delete node')
    return res.json()
  },

  async deleteEdge(fromNode: string, toNode: string) {
    const res = await fetchWithAuth(
      `/graph/nodes/${encodeURIComponent(fromNode)}/edges/${encodeURIComponent(toNode)}`,
      { method: 'DELETE' }
    )
    if (!res.ok) throw new Error('Failed to delete edge')
    return res.json()
  },
}

// ============================================================
// Search API
// ============================================================
export const searchApi = {
  async search(query: string, filters?: Record<string, unknown>) {
    const res = await fetchWithAuth('/search', {
      method: 'POST',
      body: JSON.stringify({ query, ...filters }),
    })
    if (!res.ok) throw new Error('Search failed')
    return res.json()
  },
}

// ============================================================
// Personas API
// ============================================================
export const personasApi = {
  async list() {
    const res = await fetchWithAuth('/personas')
    if (!res.ok) throw new Error('Failed to fetch personas')
    return res.json()
  },

  async create(data: { name: string; description?: string; systemPrompt: string; isDefault?: boolean }) {
    const res = await fetchWithAuth('/personas', {
      method: 'POST',
      body: JSON.stringify({
        name: data.name,
        description: data.description,
        system_prompt: data.systemPrompt,
        is_default: data.isDefault,
      }),
    })
    if (!res.ok) throw new Error('Failed to create persona')
    return res.json()
  },

  async update(id: string, data: Partial<{ name: string; description: string; systemPrompt: string; isDefault: boolean }>) {
    const res = await fetchWithAuth(`/personas/${id}`, {
      method: 'PUT',
      body: JSON.stringify({
        name: data.name,
        description: data.description,
        system_prompt: data.systemPrompt,
        is_default: data.isDefault,
      }),
    })
    if (!res.ok) throw new Error('Failed to update persona')
    return res.json()
  },

  async delete(id: string) {
    const res = await fetchWithAuth(`/personas/${id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error('Failed to delete persona')
    return res.json()
  },
}

// ============================================================
// Memories API
// ============================================================
export const memoriesApi = {
  async list(params?: { source?: string; search?: string; category?: string }) {
    const query = new URLSearchParams()
    if (params?.source) query.set('source', params.source)
    if (params?.search) query.set('search', params.search)
    if (params?.category) query.set('category', params.category)
    const qs = query.toString()
    const res = await fetchWithAuth(`/memories${qs ? `?${qs}` : ''}`)
    if (!res.ok) throw new Error('Failed to fetch memories')
    return res.json()
  },

  async create(data: { content: string; category?: string; tags?: string[] }) {
    const res = await fetchWithAuth('/memories', {
      method: 'POST',
      body: JSON.stringify(data),
    })
    if (!res.ok) throw new Error('Failed to create memory')
    return res.json()
  },

  async update(id: string, data: Partial<{ content: string; category: string; tags: string[]; enabled: boolean }>) {
    const res = await fetchWithAuth(`/memories/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
    if (!res.ok) throw new Error('Failed to update memory')
    return res.json()
  },

  async delete(id: string) {
    const res = await fetchWithAuth(`/memories/${id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error('Failed to delete memory')
    return res.json()
  },

  async sync() {
    const res = await fetchWithAuth('/memories/sync', { method: 'POST' })
    if (!res.ok) throw new Error('Failed to sync memories')
    return res.json()
  },
}

// ============================================================
// Notes API
// ============================================================
export const notesApi = {
  async list(parentId?: string | null, tag?: string, search?: string) {
    const params = new URLSearchParams()
    if (parentId !== undefined && parentId !== null) params.append('parent_id', parentId)
    if (tag) params.append('tag', tag)
    if (search) params.append('search', search)
    const qs = params.toString()
    const res = await fetchWithAuth(`/notes${qs ? `?${qs}` : ''}`)
    if (!res.ok) throw new Error('Failed to fetch notes')
    return res.json()
  },

  async listAll() {
    const res = await fetchWithAuth('/notes/all')
    if (!res.ok) throw new Error('Failed to fetch all notes')
    return res.json()
  },

  async get(id: string) {
    const res = await fetchWithAuth(`/notes/${id}`)
    if (!res.ok) throw new Error('Failed to fetch note')
    return res.json()
  },

  async create(data: {
    title?: string
    content?: string
    parent_id?: string | null
    tags?: string[]
    is_folder?: boolean
  }) {
    const res = await fetchWithAuth('/notes', {
      method: 'POST',
      body: JSON.stringify(data),
    })
    if (!res.ok) throw new Error('Failed to create note')
    return res.json()
  },

  async update(id: string, data: {
    title?: string
    content?: string
    parent_id?: string | null
    tags?: string[]
    is_pinned?: boolean
    last_edited_by?: string
  }) {
    const res = await fetchWithAuth(`/notes/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
    if (!res.ok) throw new Error('Failed to update note')
    return res.json()
  },

  async delete(id: string) {
    const res = await fetchWithAuth(`/notes/${id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error('Failed to delete note')
    return res.json()
  },
}

// ============================================================
// Uploads API (Images)
// ============================================================
export const uploadsApi = {
  async uploadImage(file: File) {
    const formData = new FormData()
    formData.append('file', file)
    // Use getAuthHeader() for token (NOT localStorage — Zustand stores it differently)
    const res = await fetch(`${API_BASE}/uploads`, {
      method: 'POST',
      headers: { ...getAuthHeader() },
      body: formData,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Upload failed' }))
      throw new Error(err.detail || 'Image upload failed')
    }
    return res.json() as Promise<{ url: string; filename: string; size: number; content_type: string }>
  },
}

// ============================================================
// Documents API (RAG)
// ============================================================
export const documentsApi = {
  async list() {
    const res = await fetchWithAuth('/documents')
    if (!res.ok) throw new Error('Failed to fetch documents')
    return res.json()
  },

  async upload(file: File) {
    const formData = new FormData()
    formData.append('file', file)
    const res = await fetch(`${API_BASE}/documents`, {
      method: 'POST',
      headers: { ...getAuthHeader() },
      body: formData,
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Upload failed' }))
      throw new Error(err.detail || 'Upload failed')
    }
    return res.json()
  },

  async delete(id: string) {
    const res = await fetchWithAuth(`/documents/${id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error('Failed to delete document')
    return res.json()
  },
}

// ============================================================
// Users API
// ============================================================
export const usersApi = {
  async list() {
    const res = await fetchWithAuth('/users/')
    if (!res.ok) throw new Error('Failed to fetch users')
    return res.json()
  },

  async updateMe(data: { name?: string; email?: string; password?: string }) {
    const res = await fetchWithAuth('/users/me', {
      method: 'PUT',
      body: JSON.stringify(data),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Update failed' }))
      throw new Error(err.detail || 'Update failed')
    }
    return res.json()
  },

  async update(userId: string, data: { name?: string; email?: string; password?: string }) {
    const res = await fetchWithAuth(`/users/${userId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Update failed' }))
      throw new Error(err.detail || 'Update failed')
    }
    return res.json()
  },

  async create(data: { email: string; name: string; password: string }) {
    const res = await fetchWithAuth('/users/', {
      method: 'POST',
      body: JSON.stringify(data),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Create failed' }))
      throw new Error(err.detail || 'Create failed')
    }
    return res.json()
  },

  async delete(userId: string) {
    const res = await fetchWithAuth(`/users/${userId}`, { method: 'DELETE' })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Delete failed' }))
      throw new Error(err.detail || 'Delete failed')
    }
    return res.json()
  },
}

// ============================================================
// Add-ins API
// ============================================================
export const addinsApi = {
  async list() {
    const res = await fetchWithAuth('/addins')
    if (!res.ok) throw new Error('Failed to fetch add-ins')
    return res.json()
  },

  async toggle(id: string) {
    const res = await fetchWithAuth(`/addins/${id}/toggle`, { method: 'PUT' })
    if (!res.ok) throw new Error('Failed to toggle add-in')
    return res.json()
  },

  async updateConfig(id: string, settings: Record<string, unknown>) {
    const res = await fetchWithAuth(`/addins/${id}/config`, {
      method: 'PUT',
      body: JSON.stringify({ settings }),
    })
    if (!res.ok) throw new Error('Failed to update add-in config')
    return res.json()
  },

  async uninstall(id: string) {
    const res = await fetchWithAuth(`/addins/${id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error('Failed to uninstall add-in')
    return res.json()
  },

  /** Call an addin's handle_action endpoint. Generic bridge for any addin. */
  async action(addinName: string, action: string, payload: Record<string, unknown> = {}) {
    const res = await fetchWithAuth(`/addins/${addinName}/action`, {
      method: 'POST',
      body: JSON.stringify({ action, payload }),
    })
    if (!res.ok) throw new Error(`Addin action failed: ${action}`)
    return res.json()
  },

  /** Get the dynamic settings schema declared by an addin. */
  async getSettingsSchema(addinName: string) {
    const res = await fetchWithAuth(`/addins/${addinName}/settings-schema`)
    if (!res.ok) return { sections: [] }
    return res.json()
  },
}

// ============================================================
// Notifications API
// ============================================================
export const notificationsApi = {
  async list(status?: string, limit = 50, skip = 0) {
    const params = new URLSearchParams()
    if (status) params.append('status', status)
    params.append('limit', String(limit))
    params.append('skip', String(skip))
    const res = await fetchWithAuth(`/notifications/?${params}`)
    if (!res.ok) throw new Error('Failed to fetch notifications')
    return res.json()
  },

  async unreadCount() {
    const res = await fetchWithAuth('/notifications/unread-count')
    if (!res.ok) throw new Error('Failed to fetch unread count')
    return res.json()
  },

  async markRead(id: string) {
    const res = await fetchWithAuth(`/notifications/${id}/read`, { method: 'PUT' })
    if (!res.ok) throw new Error('Failed to mark notification as read')
    return res.json()
  },

  async markAllRead() {
    const res = await fetchWithAuth('/notifications/read-all', { method: 'PUT' })
    if (!res.ok) throw new Error('Failed to mark all as read')
    return res.json()
  },

  async cancel(id: string) {
    const res = await fetchWithAuth(`/notifications/${id}/cancel`, { method: 'PUT' })
    if (!res.ok) throw new Error('Failed to cancel notification')
    return res.json()
  },

  async retry(id: string) {
    const res = await fetchWithAuth(`/notifications/${id}/retry`, { method: 'PUT' })
    if (!res.ok) throw new Error('Failed to retry notification')
    return res.json()
  },

  async delete(id: string) {
    const res = await fetchWithAuth(`/notifications/${id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error('Failed to delete notification')
    return res.json()
  },
}

// ============================================================
// Schedule API
// ============================================================
export const scheduleApi = {
  async list(start?: string, end?: string, category?: string) {
    const params = new URLSearchParams()
    if (start) params.set('start', start)
    if (end) params.set('end', end)
    if (category) params.set('category', category)
    const qs = params.toString()
    const res = await fetchWithAuth(`/schedule${qs ? `?${qs}` : ''}`)
    if (!res.ok) throw new Error('Failed to fetch events')
    return res.json()
  },

  async create(data: Record<string, unknown>) {
    const res = await fetchWithAuth('/schedule', {
      method: 'POST',
      body: JSON.stringify(data),
    })
    if (!res.ok) throw new Error('Failed to create event')
    return res.json()
  },

  async update(id: string, data: Record<string, unknown>) {
    const res = await fetchWithAuth(`/schedule/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
    if (!res.ok) throw new Error('Failed to update event')
    return res.json()
  },

  async delete(id: string) {
    const res = await fetchWithAuth(`/schedule/${id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error('Failed to delete event')
    return res.json()
  },

  async upcoming(days = 7) {
    const res = await fetchWithAuth(`/schedule/upcoming?days=${days}`)
    if (!res.ok) throw new Error('Failed to fetch upcoming events')
    return res.json()
  },
}

// ============================================================
// Budget API
// ============================================================
export const budgetApi = {
  async list(days = 30, category?: string) {
    const params = new URLSearchParams({ days: String(days) })
    if (category) params.set('category', category)
    const res = await fetchWithAuth(`/budget?${params}`)
    if (!res.ok) throw new Error('Failed to fetch expenses')
    return res.json()
  },

  async add(data: { amount: number; category?: string; description?: string; date?: string; store?: string }) {
    const res = await fetchWithAuth('/budget', {
      method: 'POST',
      body: JSON.stringify(data),
    })
    if (!res.ok) throw new Error('Failed to add expense')
    return res.json()
  },

  async delete(id: string) {
    const res = await fetchWithAuth(`/budget/${id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error('Failed to delete expense')
    return res.json()
  },

  async summary(days = 30) {
    const res = await fetchWithAuth(`/budget/summary?days=${days}`)
    if (!res.ok) throw new Error('Failed to fetch summary')
    return res.json()
  },

  async setGoal(category: string, amount: number) {
    const res = await fetchWithAuth('/budget/goal', {
      method: 'POST',
      body: JSON.stringify({ category, amount }),
    })
    if (!res.ok) throw new Error('Failed to set budget goal')
    return res.json()
  },
}
