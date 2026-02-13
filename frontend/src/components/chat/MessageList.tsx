/**
 * Message list component displaying conversation messages.
 *
 * @param messages - Array of messages to render
 * @param isStreaming - Whether the assistant is currently streaming a response
 */

import type { Message } from '../../types/chat.types'
import MessageBubble from './MessageBubble'

interface Props {
  messages: Message[]
  isStreaming?: boolean
}

export default function MessageList({ messages, isStreaming = false }: Props) {
  if (messages.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-dark-text-secondary">
        <p>No messages yet. Start the conversation!</p>
      </div>
    )
  }

  return (
    <div>
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
