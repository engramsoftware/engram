/**
 * Main chat interface component.
 * Displays messages and handles user input with streaming responses.
 */

import { useEffect, useRef } from 'react'
import { useChatStore } from '../../stores/chatStore'
import { useDonationStore } from '../../stores/donationStore'
import { messagesApi, conversationsApi } from '../../services/api'
import MessageList from './MessageList'
import MessageInput from './MessageInput'
import ModelSelector from './ModelSelector'
import DonationPopup from '../DonationPopup'
import type { ImageAttachment } from '../../types/chat.types'

export default function ChatInterface() {
  const { 
    activeConversationId, 
    messages, 
    setMessages, 
    addMessage,
    updateLastMessage,
    updateLastMessageSources,
    updateLastMessageNotifications,
    updateLastMessageContext,
    updateConversation,
    isStreaming,
    setStreaming,
    setLoading 
  } = useChatStore()
  const { incrementMessages } = useDonationStore()
  
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const isFirstMessage = useRef(false)

  // Fetch messages when conversation changes
  useEffect(() => {
    if (!activeConversationId) return
    
    async function fetchMessages() {
      setLoading(true)
      try {
        const data = await messagesApi.list(activeConversationId!)
        setMessages(data)
      } catch (error) {
        console.error('Failed to fetch messages:', error)
      } finally {
        setLoading(false)
      }
    }
    
    fetchMessages()
  }, [activeConversationId, setMessages, setLoading])

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Handle sending a message with SSE streaming
  const handleSend = async (content: string, images?: ImageAttachment[]) => {
    if (!activeConversationId || (!content.trim() && (!images || images.length === 0))) return

    // Track message count for donation popup
    incrementMessages()

    // Track if this is the first message (for auto-title)
    isFirstMessage.current = messages.length === 0

    // Add user message optimistically (include images for display)
    const userMsg = {
      id: `temp-${Date.now()}`,
      conversationId: activeConversationId,
      role: 'user' as const,
      content,
      images: images || [],
      timestamp: new Date().toISOString(),
      metadata: {},
    }
    addMessage(userMsg)

    // Add placeholder for assistant response
    const assistantMsg = {
      id: `temp-assistant-${Date.now()}`,
      conversationId: activeConversationId,
      role: 'assistant' as const,
      content: '',
      timestamp: new Date().toISOString(),
      metadata: {},
    }
    addMessage(assistantMsg)

    setStreaming(true)

    try {
      // Use the API service which handles auth automatically
      const response = await messagesApi.sendMessage(activeConversationId, content, images)

      const reader = response.body?.getReader()
      if (!reader) {
        throw new Error('No response body')
      }
      
      const decoder = new TextDecoder()
      let fullContent = ''

      /** Strip hidden markers so user never sees them (complete or in-progress). */
      const stripHiddenMarkers = (text: string): string => {
        let cleaned = text
        // Strip complete [SAVE_NOTE] markers
        cleaned = cleaned.replace(/\[SAVE_NOTE:\s*[^\]]*\]\s*\n[\s\S]*?\n?\[\/SAVE_NOTE\]/g, '')
        // Strip incomplete [SAVE_NOTE] still being streamed
        cleaned = cleaned.replace(/\[SAVE_NOTE:\s*[^\]]*\][\s\S]*$/g, '')
        // Strip complete [SEND_EMAIL] markers
        cleaned = cleaned.replace(/\[SEND_EMAIL:\s*[^\]]*\]\s*\n[\s\S]*?\n?\[\/SEND_EMAIL\]/g, '')
        // Strip incomplete [SEND_EMAIL] still being streamed
        cleaned = cleaned.replace(/\[SEND_EMAIL:\s*[^\]]*\][\s\S]*$/g, '')
        // Strip complete [SCHEDULE_EMAIL] markers
        cleaned = cleaned.replace(/\[SCHEDULE_EMAIL:\s*[^\]]*\]\s*\n[\s\S]*?\n?\[\/SCHEDULE_EMAIL\]/g, '')
        // Strip incomplete [SCHEDULE_EMAIL] still being streamed
        cleaned = cleaned.replace(/\[SCHEDULE_EMAIL:\s*[^\]]*\][\s\S]*$/g, '')
        // Strip complete [ADD_EXPENSE] markers
        cleaned = cleaned.replace(/\[ADD_EXPENSE:\s*[^\]]*\]\s*\n?[\s\S]*?\n?\[\/ADD_EXPENSE\]/g, '')
        // Strip incomplete [ADD_EXPENSE] still being streamed
        cleaned = cleaned.replace(/\[ADD_EXPENSE:\s*[^\]]*\][\s\S]*$/g, '')
        // Strip complete [ADD_SCHEDULE] markers
        cleaned = cleaned.replace(/\[ADD_SCHEDULE:\s*[^\]]*\]\s*\n?[\s\S]*?\n?\[\/ADD_SCHEDULE\]/g, '')
        // Strip incomplete [ADD_SCHEDULE] still being streamed
        cleaned = cleaned.replace(/\[ADD_SCHEDULE:\s*[^\]]*\][\s\S]*$/g, '')
        return cleaned.replace(/\n{3,}/g, '\n\n').trim()
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value, { stream: true })
        const lines = chunk.split('\n')

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const parsed = JSON.parse(line.slice(6))
              // Web search sources arrive before content chunks
              if (parsed.web_sources) {
                updateLastMessageSources(parsed.web_sources)
              }
              // Context transparency metadata for collapsible panel
              if (parsed.context_metadata) {
                updateLastMessageContext(parsed.context_metadata)
              }
              // Notification confirmations arrive after stream completes
              if (parsed.notifications) {
                updateLastMessageNotifications(parsed.notifications)
              }
              if (parsed.content) {
                fullContent += parsed.content
                updateLastMessage(stripHiddenMarkers(fullContent))
              }
              if (parsed.error) {
                updateLastMessage(`Error: ${parsed.error}`)
                return
              }
              if (parsed.done) {
                // Auto-generate title from first message
                if (isFirstMessage.current) {
                  const title = content.length > 40 ? content.slice(0, 40) + '...' : content
                  try {
                    await conversationsApi.update(activeConversationId, { title })
                    updateConversation(activeConversationId, { title })
                  } catch {
                    // Non-critical - title stays as "New Chat"
                  }
                }

                // Don't re-fetch messages from server here.
                // SSE-only fields (web_sources, notifications, context_metadata)
                // aren't stored in MongoDB, so a fresh fetch would wipe them
                // and cause cards to flash then disappear. Temp IDs work fine
                // for display; real IDs load on next conversation switch.
                return
              }
            } catch {
              // Ignore parse errors for incomplete JSON
            }
          }
        }
      }
    } catch (error) {
      console.error('Streaming error:', error)
      updateLastMessage(`Error: ${error instanceof Error ? error.message : 'Failed to get response'}`)
    } finally {
      setStreaming(false)
    }
  }


  // Empty state — no conversation selected, show loading
  if (!activeConversationId) {
    return (
      <div className="flex-1 flex items-center justify-center px-4">
        <div className="text-center">
          <div className="w-10 h-10 border-2 border-indigo-500/30 border-t-indigo-500
                          rounded-full animate-spin mx-auto mb-4" />
          <p className="text-sm text-dark-text-secondary">
            Loading your conversations...
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Donation popup — shows every 50 messages unless donated */}
      <DonationPopup />

      {/* Header */}
      <div className="border-b border-dark-border px-4 py-2 flex items-center justify-between
                      bg-dark-bg-primary/80 backdrop-blur-sm">
        <ModelSelector />
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <MessageList messages={messages} isStreaming={isStreaming} />
        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="border-t border-dark-border p-2.5 sm:p-4 bg-dark-bg-primary">
        <MessageInput
          onSend={handleSend}
          disabled={isStreaming}
        />
        <p className="text-center text-[10px] text-dark-text-secondary/50 mt-1.5 sm:mt-2">
          Engram can make mistakes. Verify important information.
        </p>
      </div>
    </div>
  )
}
