/**
 * Message list component displaying conversation messages.
 *
 * @param messages - Array of messages to render
 * @param isStreaming - Whether the assistant is currently streaming a response
 * @param isLoading - Whether the conversation's messages are still being fetched
 */

import type { Message } from '../../types/chat.types'
import MessageBubble from './MessageBubble'

interface Props {
  messages: Message[]
  isStreaming?: boolean
  isLoading?: boolean
}

export default function MessageList({ messages, isStreaming = false, isLoading = false }: Props) {
  if (messages.length === 0 && isLoading) {
    return (
      <div data-testid="messages-skeleton" className="max-w-3xl mx-auto px-4 py-6 space-y-6 animate-pulse" aria-busy="true" aria-label="Loading messages">
        {[0.6, 0.85, 0.45].map((w, i) => (
          <div key={i} className="space-y-2">
            <div className="h-3 rounded bg-dark-bg-secondary" style={{ width: `${w * 100}%` }} />
            <div className="h-3 rounded bg-dark-bg-secondary" style={{ width: `${w * 70}%` }} />
          </div>
        ))}
      </div>
    )
  }

  if (messages.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-dark-text-secondary">
        <p>No messages yet. Start the conversation!</p>
      </div>
    )
  }

  return (
    <div className="py-4">
      {messages.map((message, idx) => (
        <MessageBubble
          key={message.id}
          message={message}
          isThinking={isStreaming && idx === messages.length - 1}
        />
      ))}
    </div>
  )
}
