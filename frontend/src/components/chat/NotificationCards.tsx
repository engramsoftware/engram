/**
 * Inline notification confirmation cards shown in chat messages.
 * Displays when Engram sends or schedules an email notification,
 * so the user can see what was sent/scheduled without leaving the chat.
 *
 * @param notifications - Array of notification summaries from the SSE stream
 */

import { Mail, Clock, Check, AlertTriangle } from 'lucide-react'
import type { NotificationSummary } from '../../types/chat.types'

interface Props {
  notifications: NotificationSummary[]
}

export default function NotificationCards({ notifications }: Props) {
  if (!notifications || notifications.length === 0) return null

  return (
    <div className="flex flex-col gap-1.5 mt-2">
      {notifications.map((notif, i) => {
        const isSent = notif.status === 'sent'
        const isScheduled = notif.status === 'scheduled'
        const isFailed = notif.status === 'failed'

        return (
          <div
            key={i}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-xs border ${
              isSent
                ? 'bg-green-500/10 border-green-500/20 text-green-300'
                : isScheduled
                  ? 'bg-blue-500/10 border-blue-500/20 text-blue-300'
                  : 'bg-red-500/10 border-red-500/20 text-red-300'
            }`}
          >
            {isSent && <Check size={14} className="flex-shrink-0" />}
            {isScheduled && <Clock size={14} className="flex-shrink-0" />}
            {isFailed && <AlertTriangle size={14} className="flex-shrink-0" />}
            <Mail size={14} className="flex-shrink-0 opacity-60" />
            <span className="truncate font-medium">{notif.subject}</span>
            <span className="ml-auto flex-shrink-0 opacity-70">
              {isSent && 'Sent'}
              {isScheduled && notif.scheduled_at && (
                <>Scheduled for {new Date(notif.scheduled_at).toLocaleString(undefined, {
                  month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                })}</>
              )}
              {isFailed && 'Failed'}
            </span>
          </div>
        )
      })}
    </div>
  )
}
