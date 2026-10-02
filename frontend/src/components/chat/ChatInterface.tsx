/**
 * Main chat interface component.
 * Displays messages and handles user input with streaming responses.
 */

import { useEffect, useRef, useState } from 'react'
import { Menu } from 'lucide-react'
import { useChatStore } from '../../stores/chatStore'
import { useDonationStore } from '../../stores/donationStore'
import { useUIStore } from '../../stores/uiStore'
import { messagesApi, conversationsApi } from '../../services/api'
import MessageList from './MessageList'
import MessageInput from './MessageInput'
import ModelSelector from './ModelSelector'
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
    isLoading,
    setLoading,
    conversations,
    conversationsStatus,
    loadConversations,
    addConversation,
    setActiveConversation,
  } = useChatStore()
  const { incrementMessages } = useDonationStore()
  const { sidebarOpen, toggleSidebar } = useUIStore()

  const scrollRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const isFirstMessage = useRef(false)
  // Follow new content only while the user is at (or near) the bottom
  const stickToBottom = useRef(true)
  const [loadError, setLoadError] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  // Fetch messages when conversation changes (or on Retry)
  useEffect(() => {
    if (!activeConversationId) return
    let cancelled = false
    stickToBottom.current = true

    async function fetchMessages() {
      setLoading(true)
      setLoadError(false)
      try {
        const data = await messagesApi.list(activeConversationId!)
        // Ignore a response that arrives after the user switched conversations
        if (!cancelled) setMessages(data)
      } catch (error) {
        console.error('Failed to fetch messages:', error)
        if (!cancelled) setLoadError(true)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchMessages()
    return () => { cancelled = true }
  }, [activeConversationId, reloadKey, setMessages, setLoading])

  const handleScroll = () => {
    const el = scrollRef.current
    if (el) stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  // Auto-scroll to bottom; instant while tokens stream (smooth per token stutters)
  useEffect(() => {
    if (!stickToBottom.current) return
    messagesEndRef.current?.scrollIntoView({ behavior: isStreaming ? 'auto' : 'smooth' })
  }, [messages, isStreaming])

  const handleNewChat = async () => {
    try {
      const conv = await conversationsApi.create()
      addConversation(conv)
      setActiveConversation(conv.id)
    } catch (error) {
      console.error('Failed to create conversation:', error)
    }
  }

  // Handle sending a message with SSE streaming
  const handleSend = async (content: string, images?: ImageAttachment[]) => {
    if (!activeConversationId || (!content.trim() && (!images || images.length === 0))) return

    // Track message count for donation popup
    incrementMessages()

    // Track if this is the first message (for auto-title)
    isFirstMessage.current = messages.length === 0
    stickToBottom.current = true

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


  const menuButton = (
    <button
      onClick={toggleSidebar}
      className={`${sidebarOpen ? 'md:hidden' : ''} p-1.5 rounded-lg text-dark-text-secondary
                  hover:text-dark-text-primary hover:bg-dark-bg-secondary transition-colors`}
      aria-label="Open menu"
    >
      <Menu size={20} />
    </button>
  )

  // No conversation selected: loading, failed, empty, or none picked yet
  if (!activeConversationId) {
    let body
    if (conversationsStatus === 'error') {
      body = (
        <>
          <p className="text-sm text-dark-text-secondary mb-3">Couldn't load your conversations.</p>
          <button
            onClick={loadConversations}
            className="px-3 py-1.5 rounded-lg text-sm bg-dark-bg-secondary hover:bg-dark-border text-dark-text-primary transition-colors"
          >
            Retry
          </button>
        </>
      )
    } else if (conversationsStatus === 'loaded') {
      body = (
        <>
          <p className="text-sm text-dark-text-secondary mb-3">
            {conversations.length === 0 ? 'No conversations yet.' : 'Pick a conversation from the sidebar, or start a new one.'}
          </p>
          <button
            onClick={handleNewChat}
            className="px-3 py-1.5 rounded-lg text-sm bg-dark-accent-primary hover:bg-dark-accent-hover text-white transition-colors"
          >
            Start a new chat
          </button>
        </>
      )
    } else {
      body = (
        <>
          <div className="w-10 h-10 border-2 border-indigo-500/30 border-t-indigo-500
                          rounded-full animate-spin mx-auto mb-4" />
          <p className="text-sm text-dark-text-secondary">
            Loading your conversations...
          </p>
        </>
      )
    }
    return (
      <div className="flex flex-col h-full">
        <div className={`${sidebarOpen ? 'md:hidden' : ''} px-4 py-2 flex items-center`}>{menuButton}</div>
        <div className="flex-1 flex items-center justify-center px-4">
          <div className="text-center">{body}</div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header. `relative z-10`: backdrop-blur makes this a stacking context, and
          without a z-index, positioned message content (code blocks) painted over
          the model dropdown and swallowed taps on it. */}
      <div className="relative z-10 border-b border-dark-border px-4 py-2 flex items-center gap-2
                      bg-dark-bg-primary/80 backdrop-blur-sm">
        {menuButton}
        <ModelSelector />
      </div>

      {/* Messages */}
      <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto">
        {loadError && messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center gap-3 px-4 text-center">
            <p className="text-sm text-dark-text-secondary">Couldn't load this conversation.</p>
            <button
              onClick={() => setReloadKey(k => k + 1)}
              className="px-3 py-1.5 rounded-lg text-sm bg-dark-bg-secondary hover:bg-dark-border text-dark-text-primary transition-colors"
            >
              Retry
            </button>
          </div>
        ) : (
          <MessageList messages={messages} isStreaming={isStreaming} isLoading={isLoading} />
        )}
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
