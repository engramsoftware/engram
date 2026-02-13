/**
 * Chat state management using Zustand.
 * Handles conversations, messages, and active chat state.
 */

import { create } from 'zustand'
import type { Conversation, Message, WebSource, NotificationSummary, ContextMetadata } from '../types/chat.types'

interface ChatState {
  // Conversations list
  conversations: Conversation[]
  activeConversationId: string | null
  
  // Messages for active conversation
  messages: Message[]
  isLoading: boolean
  isStreaming: boolean
  
  // Actions
  setConversations: (conversations: Conversation[]) => void
  addConversation: (conversation: Conversation) => void
  updateConversation: (id: string, updates: Partial<Conversation>) => void
  removeConversation: (id: string) => void
  
  setActiveConversation: (id: string | null) => void
  setMessages: (messages: Message[]) => void
  addMessage: (message: Message) => void
  updateLastMessage: (content: string) => void
  updateLastMessageSources: (sources: WebSource[]) => void
  updateLastMessageNotifications: (notifications: NotificationSummary[]) => void
  updateLastMessageContext: (context: ContextMetadata) => void
  
  setLoading: (loading: boolean) => void
  setStreaming: (streaming: boolean) => void
}

export const useChatStore = create<ChatState>((set) => ({
  conversations: [],
  activeConversationId: null,
  messages: [],
  isLoading: false,
  isStreaming: false,

  setConversations: (conversations) => set({ conversations }),
  
  addConversation: (conversation) => set((state) => ({
    conversations: [conversation, ...state.conversations],
  })),
  
  updateConversation: (id, updates) => set((state) => ({
    conversations: state.conversations.map((c) =>
      c.id === id ? { ...c, ...updates } : c
    ),
  })),
  
  removeConversation: (id) => set((state) => ({
    conversations: state.conversations.filter((c) => c.id !== id),
    activeConversationId: state.activeConversationId === id 
      ? null 
      : state.activeConversationId,
  })),

  setActiveConversation: (id) => set({ 
    activeConversationId: id,
    messages: [],
  }),
  
  setMessages: (messages) => set({ messages }),
  
  addMessage: (message) => set((state) => ({
    messages: [...state.messages, message],
  })),
  
  updateLastMessage: (content) => set((state) => {
    const messages = [...state.messages]
    if (messages.length > 0) {
      const last = messages[messages.length - 1]
      messages[messages.length - 1] = { ...last, content }
    }
    return { messages }
  }),

  updateLastMessageSources: (sources) => set((state) => {
    const messages = [...state.messages]
    if (messages.length > 0) {
      const last = messages[messages.length - 1]
      messages[messages.length - 1] = { ...last, web_sources: sources }
    }
    return { messages }
  }),

  updateLastMessageNotifications: (notifications) => set((state) => {
    const messages = [...state.messages]
    if (messages.length > 0) {
      const last = messages[messages.length - 1]
      messages[messages.length - 1] = { ...last, notifications }
    }
    return { messages }
  }),

  updateLastMessageContext: (context) => set((state) => {
    const messages = [...state.messages]
    if (messages.length > 0) {
      const last = messages[messages.length - 1]
      messages[messages.length - 1] = { ...last, context_metadata: context }
    }
    return { messages }
  }),

  setLoading: (isLoading) => set({ isLoading }),
  setStreaming: (isStreaming) => set({ isStreaming }),
}))
