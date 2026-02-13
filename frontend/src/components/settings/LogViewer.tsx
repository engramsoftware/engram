/**
 * Real-time log viewer component.
 *
 * Fetches recent logs from the backend buffer, streams new entries via SSE,
 * and provides level filtering, text search, and auto-scroll.
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Loader2, Search, Pause, Play, Trash2, ArrowDown, RefreshCw
} from 'lucide-react'
import { settingsApi } from '../../services/api'
import { useAuthStore } from '../../stores/authStore'

// ============================================================
// Types
// ============================================================

interface LogEntry {
  timestamp: number
  level: string
  logger: string
  message: string
}

// ============================================================
// Constants
// ============================================================

const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const

const LEVEL_STYLES: Record<string, { text: string; bg: string; dot: string }> = {
  DEBUG:    { text: 'text-blue-400',   bg: 'bg-blue-500/10',   dot: 'bg-blue-400' },
  INFO:     { text: 'text-green-400',  bg: 'bg-green-500/10',  dot: 'bg-green-400' },
  WARNING:  { text: 'text-yellow-400', bg: 'bg-yellow-500/10', dot: 'bg-yellow-400' },
  ERROR:    { text: 'text-red-400',    bg: 'bg-red-500/10',    dot: 'bg-red-400' },
  CRITICAL: { text: 'text-red-300',    bg: 'bg-red-700/10',    dot: 'bg-red-500' },
}

const API_BASE = '/api'

// ============================================================
// Helpers
// ============================================================

function formatTimestamp(ts: number): string {
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
    + '.' + String(d.getMilliseconds()).padStart(3, '0')
}

function shortenLogger(name: string): string {
  // "knowledge_graph.entity_extractor" → "kg.entity_ext"
  const parts = name.split('.')
  if (parts.length <= 1) return name
  return parts.map((p, i) =>
    i === parts.length - 1 ? (p.length > 15 ? p.slice(0, 12) + '…' : p) : p.slice(0, 3)
  ).join('.')
}

// ============================================================
// Component
// ============================================================

export default function LogViewer() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isPaused, setIsPaused] = useState(false)
  const [levelFilter, setLevelFilter] = useState<string>('')
  const [searchFilter, setSearchFilter] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)
  const eventSourceRef = useRef<EventSource | null>(null)
  const { token } = useAuthStore()

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [logs, autoScroll])

  // Detect manual scroll to disable auto-scroll
  const handleScroll = useCallback(() => {
    if (!scrollRef.current) return
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 40
    setAutoScroll(isAtBottom)
  }, [])

  // Fetch initial logs
  const fetchLogs = useCallback(async () => {
    setIsLoading(true)
    try {
      const data = await settingsApi.getRecentLogs({
        limit: 300,
        level: levelFilter || undefined,
        search: searchFilter || undefined,
      })
      setLogs(data)
    } catch (err) {
      console.error('Failed to fetch logs:', err)
    } finally {
      setIsLoading(false)
    }
  }, [levelFilter, searchFilter])

  // Initial load
  useEffect(() => {
    fetchLogs()
  }, [fetchLogs])

  // SSE streaming for real-time logs
  useEffect(() => {
    if (isPaused) {
      // Close existing connection when paused
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
      return
    }

    const params = new URLSearchParams()
    if (levelFilter) params.append('level', levelFilter)
    if (token) params.append('token', token)

    const url = `${API_BASE}/settings/logs/stream?${params}`
    const es = new EventSource(url)
    eventSourceRef.current = es

    es.onmessage = (event) => {
      try {
        const entry: LogEntry = JSON.parse(event.data)
        // Apply client-side search filter for SSE entries
        if (searchFilter && !entry.message.toLowerCase().includes(searchFilter.toLowerCase())) {
          return
        }
        setLogs(prev => {
          const next = [...prev, entry]
          // Cap at 500 entries in the UI
          if (next.length > 500) return next.slice(next.length - 500)
          return next
        })
      } catch {
        // ignore parse errors
      }
    }

    es.onerror = () => {
      // EventSource auto-reconnects, but log the error
      console.warn('Log stream disconnected, reconnecting...')
    }

    return () => {
      es.close()
      eventSourceRef.current = null
    }
  }, [isPaused, levelFilter, searchFilter, token])

  const clearLogs = () => setLogs([])

  // Count by level for the filter badges
  const levelCounts: Record<string, number> = {}
  for (const log of logs) {
    levelCounts[log.level] = (levelCounts[log.level] || 0) + 1
  }

  return (
    <div className="flex flex-col rounded-lg border border-dark-border bg-dark-bg-secondary overflow-hidden"
         style={{ height: '500px' }}>
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-dark-border/50 bg-dark-bg-secondary flex-shrink-0 flex-wrap">
        {/* Play/Pause */}
        <button
          onClick={() => setIsPaused(!isPaused)}
          className={`p-1.5 rounded transition-colors ${
            isPaused
              ? 'text-yellow-400 bg-yellow-500/10 hover:bg-yellow-500/20'
              : 'text-green-400 bg-green-500/10 hover:bg-green-500/20'
          }`}
          title={isPaused ? 'Resume streaming' : 'Pause streaming'}
        >
          {isPaused ? <Play size={14} /> : <Pause size={14} />}
        </button>

        {/* Refresh */}
        <button
          onClick={fetchLogs}
          className="p-1.5 rounded text-dark-text-secondary hover:text-dark-text-primary
                     hover:bg-dark-bg-primary transition-colors"
          title="Refresh logs"
        >
          <RefreshCw size={14} />
        </button>

        {/* Clear */}
        <button
          onClick={clearLogs}
          className="p-1.5 rounded text-dark-text-secondary hover:text-red-400
                     hover:bg-red-500/10 transition-colors"
          title="Clear log view"
        >
          <Trash2 size={14} />
        </button>

        {/* Divider */}
        <div className="w-px h-5 bg-dark-border/50" />

        {/* Level filters */}
        {LOG_LEVELS.map(lvl => {
          const style = LEVEL_STYLES[lvl]
          const count = levelCounts[lvl] || 0
          const isActive = levelFilter === lvl
          return (
            <button
              key={lvl}
              onClick={() => setLevelFilter(isActive ? '' : lvl)}
              className={`text-[10px] px-2 py-1 rounded font-medium transition-colors ${
                isActive
                  ? `${style.bg} ${style.text} ring-1 ring-current`
                  : 'text-dark-text-secondary/60 hover:text-dark-text-secondary'
              }`}
              title={`${isActive ? 'Show all' : `Filter to ${lvl}+`}`}
            >
              {lvl} {count > 0 && <span className="opacity-60">({count})</span>}
            </button>
          )
        })}

        {/* Divider */}
        <div className="w-px h-5 bg-dark-border/50" />

        {/* Search */}
        <div className="relative flex-1 min-w-[120px] max-w-[250px]">
          <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-dark-text-secondary/40" />
          <input
            type="text"
            value={searchFilter}
            onChange={(e) => setSearchFilter(e.target.value)}
            placeholder="Filter logs..."
            className="w-full pl-7 pr-2 py-1 bg-dark-bg-primary border border-dark-border/50 rounded
                       text-[11px] text-dark-text-primary placeholder:text-dark-text-secondary/30
                       focus:outline-none focus:border-dark-accent-primary/40 transition-colors"
          />
        </div>

        {/* Status */}
        <div className="flex items-center gap-1.5 ml-auto text-[10px] text-dark-text-secondary/50">
          {!isPaused && (
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
              Live
            </span>
          )}
          <span>{logs.length} entries</span>
        </div>
      </div>

      {/* Log entries */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto font-mono text-[11px] leading-[1.6]"
      >
        {isLoading && logs.length === 0 ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 size={16} className="animate-spin text-dark-text-secondary" />
          </div>
        ) : logs.length === 0 ? (
          <div className="flex items-center justify-center py-8 text-dark-text-secondary/40 text-xs">
            No log entries {levelFilter && `at ${levelFilter} level`}
          </div>
        ) : (
          logs.map((entry, i) => {
            const style = LEVEL_STYLES[entry.level] || LEVEL_STYLES.INFO
            return (
              <div
                key={`${entry.timestamp}-${i}`}
                className={`flex gap-0 px-3 py-0.5 hover:bg-dark-bg-primary/50 border-l-2 ${
                  entry.level === 'ERROR' || entry.level === 'CRITICAL'
                    ? 'border-l-red-500/50'
                    : entry.level === 'WARNING'
                    ? 'border-l-yellow-500/30'
                    : 'border-l-transparent'
                }`}
              >
                {/* Timestamp */}
                <span className="text-dark-text-secondary/40 flex-shrink-0 w-[85px]">
                  {formatTimestamp(entry.timestamp)}
                </span>
                {/* Level */}
                <span className={`flex-shrink-0 w-[62px] font-semibold ${style.text}`}>
                  {entry.level.padEnd(8)}
                </span>
                {/* Logger */}
                <span className="text-dark-accent-primary/50 flex-shrink-0 w-[120px] truncate"
                      title={entry.logger}>
                  {shortenLogger(entry.logger)}
                </span>
                {/* Message */}
                <span className="text-dark-text-primary/80 break-all flex-1 ml-1">
                  {entry.message.replace(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} - \S+ - \S+ - /, '')}
                </span>
              </div>
            )
          })
        )}
      </div>

      {/* Scroll-to-bottom button */}
      {!autoScroll && (
        <button
          onClick={() => {
            setAutoScroll(true)
            if (scrollRef.current) {
              scrollRef.current.scrollTop = scrollRef.current.scrollHeight
            }
          }}
          className="absolute bottom-14 right-6 p-2 rounded-full bg-dark-accent-primary/90 text-white
                     shadow-lg hover:bg-dark-accent-primary transition-colors"
          title="Scroll to bottom"
        >
          <ArrowDown size={14} />
        </button>
      )}
    </div>
  )
}
