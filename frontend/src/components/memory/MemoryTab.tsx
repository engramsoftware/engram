/**
 * Unified memory tab showing ALL memories (manual + autonomous).
 *
 * Supports filtering by source, semantic search, creating manual
 * memories, and deleting from all stores.
 */

import { useState, useEffect, useCallback } from 'react'
import { Plus, Trash2, Search, RefreshCw, Brain, User, ToggleLeft, ToggleRight } from 'lucide-react'
import { memoriesApi } from '../../services/api'
import type { Memory } from '../../types/addin.types'

type SourceFilter = 'all' | 'manual' | 'autonomous'

export default function MemoryTab() {
  const [memories, setMemories] = useState<Memory[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isSyncing, setIsSyncing] = useState(false)
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchActive, setSearchActive] = useState(false)
  const [newMemory, setNewMemory] = useState({ content: '', category: 'general' })
  const [syncStats, setSyncStats] = useState<string | null>(null)

  const fetchMemories = useCallback(async () => {
    setIsLoading(true)
    try {
      const params: { source?: string; search?: string } = {}
      if (sourceFilter !== 'all') params.source = sourceFilter
      if (searchActive && searchQuery.trim()) params.search = searchQuery.trim()
      const data = await memoriesApi.list(params)
      setMemories(data)
    } catch (error) {
      console.error('Failed to fetch memories:', error)
    } finally {
      setIsLoading(false)
    }
  }, [sourceFilter, searchActive, searchQuery])

  useEffect(() => {
    fetchMemories()
  }, [fetchMemories])

  const handleSearch = () => {
    if (searchQuery.trim()) {
      setSearchActive(true)
    }
  }

  const clearSearch = () => {
    setSearchQuery('')
    setSearchActive(false)
  }

  const handleCreate = async () => {
    if (!newMemory.content) return
    try {
      await memoriesApi.create(newMemory)
      setNewMemory({ content: '', category: 'general' })
      fetchMemories()
    } catch (error) {
      console.error('Failed to create memory:', error)
    }
  }

  const handleToggle = async (id: string, enabled: boolean) => {
    try {
      await memoriesApi.update(id, { enabled: !enabled })
      fetchMemories()
    } catch (error) {
      console.error('Failed to toggle memory:', error)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this memory? This removes it from all stores.')) return
    try {
      await memoriesApi.delete(id)
      fetchMemories()
    } catch (error) {
      console.error('Failed to delete memory:', error)
    }
  }

  const handleSync = async () => {
    setIsSyncing(true)
    setSyncStats(null)
    try {
      const stats = await memoriesApi.sync()
      setSyncStats(
        `Synced: ${stats.added_to_chroma} added, ${stats.removed_from_chroma} removed, ${stats.already_synced} OK`
      )
      fetchMemories()
    } catch (error) {
      console.error('Failed to sync memories:', error)
      setSyncStats('Sync failed')
    } finally {
      setIsSyncing(false)
      setTimeout(() => setSyncStats(null), 5000)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSearch()
    if (e.key === 'Escape') clearSearch()
  }

  const manualCount = memories.filter(m => m.source === 'manual').length
  const autoCount = memories.filter(m => m.source === 'autonomous').length

  return (
    <div className="h-full overflow-y-auto p-6 max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <h1 className="text-2xl font-semibold text-dark-text-primary">Memories</h1>
        <button
          onClick={handleSync}
          disabled={isSyncing}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded
                     bg-dark-bg-secondary border border-dark-border
                     text-dark-text-secondary hover:text-dark-text-primary
                     hover:border-dark-accent-primary transition-colors
                     disabled:opacity-50"
          title="Sync MongoDB ↔ ChromaDB"
        >
          <RefreshCw size={14} className={isSyncing ? 'animate-spin' : ''} />
          {isSyncing ? 'Syncing...' : 'Sync'}
        </button>
      </div>
      {syncStats && (
        <p className="text-xs text-dark-accent-primary mb-2">{syncStats}</p>
      )}
      <p className="text-dark-text-secondary text-sm mb-4">
        Everything the AI knows about you — manual entries and auto-learned memories.
      </p>

      {/* Search bar */}
      <div className="flex gap-2 mb-4">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-dark-text-secondary" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search memories semantically..."
            className="w-full bg-dark-bg-secondary border border-dark-border rounded
                       pl-9 pr-3 py-2 text-sm text-dark-text-primary
                       placeholder:text-dark-text-secondary/50"
          />
        </div>
        {searchActive ? (
          <button
            onClick={clearSearch}
            className="px-3 py-2 text-sm rounded bg-dark-bg-secondary border
                       border-dark-border text-dark-text-secondary hover:text-dark-text-primary"
          >
            Clear
          </button>
        ) : (
          <button
            onClick={handleSearch}
            disabled={!searchQuery.trim()}
            className="px-3 py-2 text-sm rounded bg-dark-accent-primary
                       hover:bg-dark-accent-hover text-white disabled:opacity-50"
          >
            Search
          </button>
        )}
      </div>

      {/* Source filter tabs */}
      <div className="flex gap-1 mb-4 bg-dark-bg-secondary rounded-lg p-1 border border-dark-border">
        {([
          { key: 'all' as SourceFilter, label: 'All', icon: null as null, count: memories.length },
          { key: 'manual' as SourceFilter, label: 'Manual', icon: User, count: manualCount },
          { key: 'autonomous' as SourceFilter, label: 'Auto-learned', icon: Brain, count: autoCount },
        ]).map(({ key, label, icon: Icon, count }) => (
          <button
            key={key}
            onClick={() => setSourceFilter(key)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded transition-colors flex-1 justify-center
              ${sourceFilter === key
                ? 'bg-dark-accent-primary text-white'
                : 'text-dark-text-secondary hover:text-dark-text-primary'
              }`}
          >
            {Icon && <Icon size={14} />}
            {label}
            <span className={`text-xs ml-1 ${sourceFilter === key ? 'text-white/70' : 'text-dark-text-secondary/60'}`}>
              {count}
            </span>
          </button>
        ))}
      </div>

      {/* Create new manual memory */}
      <div className="bg-dark-bg-secondary rounded-lg border border-dark-border p-4 mb-6">
        <div className="space-y-3">
          <textarea
            value={newMemory.content}
            onChange={(e) => setNewMemory({ ...newMemory, content: e.target.value })}
            placeholder="Add something for the AI to remember..."
            rows={2}
            className="w-full bg-dark-bg-primary border border-dark-border rounded
                       px-3 py-2 text-sm text-dark-text-primary resize-none"
          />
          <div className="flex gap-3">
            <select
              value={newMemory.category}
              onChange={(e) => setNewMemory({ ...newMemory, category: e.target.value })}
              className="bg-dark-bg-primary border border-dark-border rounded
                         px-3 py-2 text-sm text-dark-text-primary"
            >
              <option value="general">General</option>
              <option value="preferences">Preferences</option>
              <option value="personal">Personal</option>
              <option value="work">Work</option>
            </select>
            <button
              onClick={handleCreate}
              disabled={!newMemory.content.trim()}
              className="flex items-center gap-2 px-4 py-2 bg-dark-accent-primary
                         hover:bg-dark-accent-hover rounded text-white text-sm
                         disabled:opacity-50"
            >
              <Plus size={16} /> Add Memory
            </button>
          </div>
        </div>
      </div>

      {/* Memory list */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <RefreshCw size={20} className="animate-spin text-dark-text-secondary" />
        </div>
      ) : (
        <div className="space-y-2">
          {memories.map((memory) => (
            <div
              key={memory.id}
              className={`bg-dark-bg-secondary rounded-lg border border-dark-border p-3
                         ${!memory.enabled ? 'opacity-50' : ''}`}
            >
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm text-dark-text-primary flex-1 leading-relaxed">
                  {memory.content}
                </p>
                <div className="flex items-center gap-1.5 shrink-0">
                  {memory.source === 'manual' && (
                    <button
                      onClick={() => handleToggle(memory.id, memory.enabled)}
                      className="text-dark-text-secondary hover:text-dark-accent-primary"
                      title={memory.enabled ? 'Disable' : 'Enable'}
                    >
                      {memory.enabled ? <ToggleRight size={18} /> : <ToggleLeft size={18} />}
                    </button>
                  )}
                  <button
                    onClick={() => handleDelete(memory.id)}
                    className="text-dark-text-secondary hover:text-red-400"
                    title="Delete from all stores"
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
              <div className="mt-2 flex items-center gap-2 flex-wrap">
                <span className={`text-xs px-2 py-0.5 rounded font-medium
                  ${memory.source === 'manual'
                    ? 'bg-blue-500/15 text-blue-400'
                    : 'bg-purple-500/15 text-purple-400'
                  }`}
                >
                  {memory.source === 'manual' ? 'Manual' : 'Auto'}
                </span>
                <span className="text-xs px-2 py-0.5 bg-dark-bg-primary rounded text-dark-text-secondary">
                  {memory.memory_type}
                </span>
                {memory.confidence < 1.0 && (
                  <span className="text-xs text-dark-text-secondary/60">
                    {Math.round(memory.confidence * 100)}%
                  </span>
                )}
              </div>
            </div>
          ))}

          {memories.length === 0 && (
            <p className="text-center text-dark-text-secondary py-8">
              {searchActive ? 'No memories match your search' : 'No memories yet'}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
