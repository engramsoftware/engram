/**
 * Conversation list component with date grouping.
 * Groups conversations by Today, Yesterday, Last 7 days, etc.
 */

import { isToday, isYesterday, isThisWeek, isThisMonth } from 'date-fns'
import { useChatStore } from '../../stores/chatStore'
import { useUIStore } from '../../stores/uiStore'
import type { Conversation } from '../../types/chat.types'
import ConversationItem from './ConversationItem'

interface Props {
  conversations: Conversation[]
}

// Group conversations by date
function groupConversations(conversations: Conversation[]) {
  const groups: Record<string, Conversation[]> = {
    Today: [],
    Yesterday: [],
    'Last 7 days': [],
    'Last 30 days': [],
    Older: [],
  }

  conversations.forEach((conv) => {
    const date = new Date(conv.updatedAt)
    if (isToday(date)) {
      groups.Today.push(conv)
    } else if (isYesterday(date)) {
      groups.Yesterday.push(conv)
    } else if (isThisWeek(date)) {
      groups['Last 7 days'].push(conv)
    } else if (isThisMonth(date)) {
      groups['Last 30 days'].push(conv)
    } else {
      groups.Older.push(conv)
    }
  })

  return groups
}

export default function ConversationList({ conversations }: Props) {
  const { activeConversationId, setActiveConversation } = useChatStore()
  const { setActiveTab, setSidebarOpen } = useUIStore()

  const groups = groupConversations(conversations)

  const handleSelect = (id: string) => {
    setActiveConversation(id)
    setActiveTab('chat')
    // Close sidebar on mobile after selecting a conversation
    if (window.innerWidth < 768) setSidebarOpen(false)
  }

  return (
    <div className="space-y-3">
      {Object.entries(groups).map(([label, convs]) => {
        if (convs.length === 0) return null
        
        return (
          <div key={label}>
            <div className="text-xs text-dark-text-secondary px-2 py-1 font-medium">
              {label}
            </div>
            <div className="space-y-0.5">
              {convs.map((conv) => (
                <ConversationItem
                  key={conv.id}
                  conversation={conv}
                  isActive={conv.id === activeConversationId}
                  onSelect={() => handleSelect(conv.id)}
                />
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
