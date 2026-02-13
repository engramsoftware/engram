/**
 * Notifications panel — shows all email notifications Engram has sent or scheduled.
 * Users can see status (sent/pending/failed/cancelled), cancel pending ones,
 * retry failed ones, and delete any notification.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Bell, Mail, Clock, Check, AlertTriangle,
  Trash2, RefreshCw, Ban, CheckCheck, Filter,
  Loader2,
} from 'lucide-react'
import { notificationsApi } from '../../services/api'

interface Notification {
  id: string
  subject: string
  body: string
  status: 'pending' | 'sent' | 'failed' | 'cancelled'
  scheduled_at: string | null
  sent_at: string | null
  created_at: string
  conversation_id: string | null
  error: string | null
  read: boolean
}

type StatusFilter = 'all' | 'pending' | 'sent' | 'failed' | 'cancelled'

/** Format a date string to a human-readable relative or absolute time. */
function formatTime(dateStr: string | null): string {
  if (!dateStr) return '—'
  const date = new Date(dateStr)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  // Future dates (scheduled)
  if (diffMs < 0) {
    const futureMins = Math.abs(diffMins)
    if (futureMins < 60) return `in ${futureMins}m`
    const futureHours = Math.abs(diffHours)
    if (futureHours < 24) return `in ${futureHours}h`
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  }

  // Past dates
  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

/** Status badge component. */
function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { icon: typeof Check; color: string; bg: string; label: string }> = {
    sent: { icon: Check, color: 'text-green-400', bg: 'bg-green-400/10', label: 'Sent' },
    pending: { icon: Clock, color: 'text-yellow-400', bg: 'bg-yellow-400/10', label: 'Scheduled' },
    failed: { icon: AlertTriangle, color: 'text-red-400', bg: 'bg-red-400/10', label: 'Failed' },
    cancelled: { icon: Ban, color: 'text-gray-400', bg: 'bg-gray-400/10', label: 'Cancelled' },
  }
  const c = config[status] || config.sent
  const Icon = c.icon
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium ${c.color} ${c.bg}`}>
      <Icon size={10} />
      {c.label}
    </span>
  )
}

export default function NotificationsTab() {
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [total, setTotal] = useState(0)
  const [unread, setUnread] = useState(0)
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [isLoading, setIsLoading] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  const fetchNotifications = useCallback(async () => {
    try {
      const status = filter === 'all' ? undefined : filter
      const data = await notificationsApi.list(status)
      setNotifications(data.notifications)
      setTotal(data.total)
      setUnread(data.unread)
    } catch (err) {
      console.error('Failed to fetch notifications:', err)
    } finally {
      setIsLoading(false)
    }
  }, [filter])

  useEffect(() => {
    fetchNotifications()
    // Poll every 30s for new notifications
    const interval = setInterval(fetchNotifications, 30000)
    return () => clearInterval(interval)
  }, [fetchNotifications])

  /** Mark a single notification as read when expanded. */
  const handleExpand = async (id: string) => {
    const next = expandedId === id ? null : id
    setExpandedId(next)
    if (next) {
      const notif = notifications.find(n => n.id === id)
      if (notif && !notif.read) {
        try {
          await notificationsApi.markRead(id)
          setNotifications(prev =>
            prev.map(n => n.id === id ? { ...n, read: true } : n)
          )
          setUnread(prev => Math.max(0, prev - 1))
        } catch { /* ignore */ }
      }
    }
  }

  /** Mark all as read. */
  const handleMarkAllRead = async () => {
    try {
      await notificationsApi.markAllRead()
      setNotifications(prev => prev.map(n => ({ ...n, read: true })))
      setUnread(0)
    } catch (err) {
      console.error('Failed to mark all as read:', err)
    }
  }

  /** Cancel a pending notification. */
  const handleCancel = async (id: string) => {
    setActionLoading(id)
    try {
      await notificationsApi.cancel(id)
      setNotifications(prev =>
        prev.map(n => n.id === id ? { ...n, status: 'cancelled' } : n)
      )
    } catch (err) {
      console.error('Failed to cancel:', err)
    } finally {
      setActionLoading(null)
    }
  }

  /** Retry a failed notification. */
  const handleRetry = async (id: string) => {
    setActionLoading(id)
    try {
      await notificationsApi.retry(id)
      setNotifications(prev =>
        prev.map(n => n.id === id ? { ...n, status: 'pending', error: null } : n)
      )
    } catch (err) {
      console.error('Failed to retry:', err)
    } finally {
      setActionLoading(null)
    }
  }

  /** Delete a notification. */
  const handleDelete = async (id: string) => {
    setActionLoading(id)
    try {
      await notificationsApi.delete(id)
      setNotifications(prev => prev.filter(n => n.id !== id))
      setTotal(prev => prev - 1)
    } catch (err) {
      console.error('Failed to delete:', err)
    } finally {
      setActionLoading(null)
    }
  }

  const filters: { value: StatusFilter; label: string }[] = [
    { value: 'all', label: 'All' },
    { value: 'pending', label: 'Scheduled' },
    { value: 'sent', label: 'Sent' },
    { value: 'failed', label: 'Failed' },
  ]

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 px-4 sm:px-6 pt-4 pb-3 border-b border-dark-border">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <Bell size={18} className="text-dark-accent-primary" />
            <h1 className="text-base sm:text-lg font-semibold text-dark-text-primary">
              Notifications
            </h1>
            {unread > 0 && (
              <span className="bg-dark-accent-primary text-white text-[10px] font-bold px-1.5 py-0.5 rounded-full min-w-[18px] text-center">
                {unread}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {unread > 0 && (
              <button
                onClick={handleMarkAllRead}
                className="flex items-center gap-1 px-2 py-1 text-xs text-dark-text-secondary
                           hover:text-dark-text-primary transition-colors"
                title="Mark all as read"
              >
                <CheckCheck size={14} />
                Mark all read
              </button>
            )}
          </div>
        </div>

        {/* Filter tabs */}
        <div className="flex items-center gap-1">
          <Filter size={12} className="text-dark-text-secondary mr-1" />
          {filters.map(f => (
            <button
              key={f.value}
              onClick={() => { setFilter(f.value); setIsLoading(true) }}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                filter === f.value
                  ? 'bg-dark-accent-primary/20 text-dark-accent-primary font-medium'
                  : 'text-dark-text-secondary hover:text-dark-text-primary hover:bg-dark-bg-secondary'
              }`}
            >
              {f.label}
            </button>
          ))}
          <span className="text-[10px] text-dark-text-secondary/50 ml-auto">
            {total} total
          </span>
        </div>
      </div>

      {/* Notification list */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 size={20} className="animate-spin text-dark-text-secondary" />
          </div>
        ) : notifications.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-dark-text-secondary">
            <Mail size={32} className="mb-3 opacity-30" />
            <p className="text-sm">No notifications yet</p>
            <p className="text-xs mt-1 opacity-70">
              Ask Engram to email or remind you about something
            </p>
          </div>
        ) : (
          <div className="divide-y divide-dark-border/30">
            {notifications.map(notif => (
              <div
                key={notif.id}
                className={`px-4 sm:px-6 py-3 cursor-pointer transition-colors hover:bg-dark-bg-secondary/50 ${
                  !notif.read ? 'bg-dark-accent-primary/5' : ''
                }`}
                onClick={() => handleExpand(notif.id)}
              >
                {/* Summary row */}
                <div className="flex items-start gap-3">
                  {/* Unread dot */}
                  <div className="flex-shrink-0 mt-1.5">
                    {!notif.read ? (
                      <div className="w-2 h-2 rounded-full bg-dark-accent-primary" />
                    ) : (
                      <div className="w-2 h-2" />
                    )}
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-sm font-medium text-dark-text-primary truncate">
                        {notif.subject}
                      </span>
                      <StatusBadge status={notif.status} />
                    </div>
                    <p className="text-xs text-dark-text-secondary truncate">
                      {notif.body.slice(0, 120)}
                    </p>
                    <div className="flex items-center gap-3 mt-1">
                      <span className="text-[10px] text-dark-text-secondary/60">
                        {notif.status === 'pending' && notif.scheduled_at
                          ? `Sends ${formatTime(notif.scheduled_at)}`
                          : notif.sent_at
                            ? `Sent ${formatTime(notif.sent_at)}`
                            : `Created ${formatTime(notif.created_at)}`
                        }
                      </span>
                      {notif.error && (
                        <span className="text-[10px] text-red-400 truncate">
                          {notif.error}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Expanded detail */}
                {expandedId === notif.id && (
                  <div className="mt-3 ml-5 space-y-2" onClick={e => e.stopPropagation()}>
                    {/* Full body */}
                    <div className="bg-dark-bg-primary rounded-md px-3 py-2 text-xs text-dark-text-secondary whitespace-pre-wrap max-h-48 overflow-y-auto">
                      {notif.body}
                    </div>

                    {/* Metadata */}
                    <div className="flex items-center gap-4 text-[10px] text-dark-text-secondary/50">
                      {notif.scheduled_at && (
                        <span>Scheduled: {new Date(notif.scheduled_at).toLocaleString()}</span>
                      )}
                      {notif.sent_at && (
                        <span>Sent: {new Date(notif.sent_at).toLocaleString()}</span>
                      )}
                      <span>Created: {new Date(notif.created_at).toLocaleString()}</span>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-2">
                      {notif.status === 'pending' && (
                        <button
                          onClick={() => handleCancel(notif.id)}
                          disabled={actionLoading === notif.id}
                          className="flex items-center gap-1 px-2 py-1 text-[11px] rounded
                                     bg-yellow-400/10 text-yellow-400 hover:bg-yellow-400/20
                                     disabled:opacity-50 transition-colors"
                        >
                          {actionLoading === notif.id
                            ? <Loader2 size={10} className="animate-spin" />
                            : <Ban size={10} />
                          }
                          Cancel
                        </button>
                      )}
                      {notif.status === 'failed' && (
                        <button
                          onClick={() => handleRetry(notif.id)}
                          disabled={actionLoading === notif.id}
                          className="flex items-center gap-1 px-2 py-1 text-[11px] rounded
                                     bg-blue-400/10 text-blue-400 hover:bg-blue-400/20
                                     disabled:opacity-50 transition-colors"
                        >
                          {actionLoading === notif.id
                            ? <Loader2 size={10} className="animate-spin" />
                            : <RefreshCw size={10} />
                          }
                          Retry
                        </button>
                      )}
                      <button
                        onClick={() => handleDelete(notif.id)}
                        disabled={actionLoading === notif.id}
                        className="flex items-center gap-1 px-2 py-1 text-[11px] rounded
                                   bg-red-400/10 text-red-400 hover:bg-red-400/20
                                   disabled:opacity-50 transition-colors"
                      >
                        {actionLoading === notif.id
                          ? <Loader2 size={10} className="animate-spin" />
                          : <Trash2 size={10} />
                        }
                        Delete
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
