/**
 * Single conversation item in the sidebar list.
 */

import { MessageSquare, Pin, Trash2 } from 'lucide-react'
import { useChatStore } from '../../stores/chatStore'
import { conversationsApi } from '../../services/api'
import type { Conversation } from '../../types/chat.types'

interface Props {
  conversation: Conversation
  isActive: boolean
  onSelect: () => void
}

export default function ConversationItem({ conversation, isActive, onSelect }: Props) {
  const { updateConversation, removeConversation } = useChatStore()

  const handlePin = async (e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await conversationsApi.update(conversation.id, { isPinned: !conversation.isPinned })
      updateConversation(conversation.id, { isPinned: !conversation.isPinned })
    } catch (error) {
      console.error('Failed to pin conversation:', error)
    }
  }

  const handleDelete = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('Delete this conversation?')) return
    try {
      await conversationsApi.delete(conversation.id)
      removeConversation(conversation.id)
    } catch (error) {
      console.error('Failed to delete conversation:', error)
    }
  }

  return (
    <div
      onClick={onSelect}
      className={`group flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-pointer
                  transition-colors ${
                    isActive
                      ? 'bg-dark-bg-secondary text-dark-text-primary'
                      : 'text-dark-text-secondary hover:bg-dark-bg-secondary hover:text-dark-text-primary'
                  }`}
    >
      <MessageSquare size={14} className="flex-shrink-0" />
      <span className="flex-1 truncate text-sm">{conversation.title}</span>
      
      {/* Action buttons - show on hover */}
      <div className="hidden group-hover:flex items-center gap-1">
        <button
          onClick={handlePin}
          className={`p-1 rounded hover:bg-dark-border ${
            conversation.isPinned ? 'text-dark-accent-primary' : ''
          }`}
        >
          <Pin size={12} />
        </button>
        <button
          onClick={handleDelete}
          className="p-1 rounded hover:bg-dark-border text-red-400"
        >
          <Trash2 size={12} />
        </button>
      </div>
      
      {/* Pin indicator when not hovering */}
      {conversation.isPinned && (
        <Pin size={12} className="text-dark-accent-primary group-hover:hidden" />
      )}
    </div>
  )
}
