/**
 * Sidebar component with navigation and conversation list.
 * Claude.ai-style dark theme with grouped conversations.
 */

import { useEffect, useState } from 'react'
import {
  MessageSquarePlus,
  MessageSquare,
  Search,
  Settings,
  Puzzle,
  User,
  Brain,
  BookOpen,
  StickyNote,
  FileText,
  Bell,
  GitBranch,
  Wallet,
  CalendarDays,
  Sun,
  Moon,
  Heart,
  Timer,
  Smile,
  Sparkles,
} from 'lucide-react'
import { useUIStore, ActiveTab } from '../../stores/uiStore'
import { useChatStore } from '../../stores/chatStore'
import { useAuthStore } from '../../stores/authStore'
import { useDonationStore } from '../../stores/donationStore'
import { useAddinsStore } from '../../stores/addinsStore'
import { conversationsApi, notificationsApi } from '../../services/api'
import ConversationList from '../conversations/ConversationList'

/** Map addin UI icon names to Lucide components. */
const ADDIN_ICONS: Record<string, React.ReactNode> = {
  timer: <Timer size={18} />,
  smile: <Smile size={18} />,
  default: <Sparkles size={18} />,
}

export default function Sidebar() {
  const { activeTab, setActiveTab, setSidebarOpen, theme, toggleTheme } = useUIStore()

  /** Close sidebar on mobile after navigation. */
  const closeMobileSidebar = () => {
    if (window.innerWidth < 768) setSidebarOpen(false)
  }
  const { conversations, setConversations, addConversation, setActiveConversation } = useChatStore()
  const { user, logout } = useAuthStore()
  const { hasDonated } = useDonationStore()
  const [unreadNotifs, setUnreadNotifs] = useState(0)

  // Fetch conversations on mount and auto-select the most recent one
  // so the user lands in their last chat instead of the empty welcome page
  useEffect(() => {
    async function fetchConversations() {
      try {
        const data = await conversationsApi.list()
        setConversations(data)
        // Auto-select the most recent conversation if none is active
        if (data.length > 0 && !useChatStore.getState().activeConversationId) {
          setActiveConversation(data[0].id)
        }
      } catch (error) {
        console.error('Failed to fetch conversations:', error)
      }
    }
    fetchConversations()
  }, [setConversations, setActiveConversation])

  // Poll for unread notification count every 30s
  useEffect(() => {
    async function fetchUnread() {
      try {
        const data = await notificationsApi.unreadCount()
        setUnreadNotifs(data.unread || 0)
      } catch { /* ignore if endpoint not available */ }
    }
    fetchUnread()
    const interval = setInterval(fetchUnread, 30000)
    return () => clearInterval(interval)
  }, [])

  // Create new conversation
  async function handleNewChat() {
    try {
      const conv = await conversationsApi.create()
      addConversation(conv)
      setActiveConversation(conv.id)
      setActiveTab('chat')
      closeMobileSidebar()
    } catch (error) {
      console.error('Failed to create conversation:', error)
    }
  }

  // Fetch enabled addins for dynamic sidebar tabs
  const { loaded: addinsLoaded, fetchAddins, guiAddins } = useAddinsStore()
  useEffect(() => { if (!addinsLoaded) fetchAddins() }, [addinsLoaded, fetchAddins])

  // Build dynamic GUI addin nav items
  const enabledGuiAddins = guiAddins()
  const dynamicItems: { id: ActiveTab; icon: React.ReactNode; label: string }[] = enabledGuiAddins.map(a => ({
    id: `addin:${a.internal_name || a.name}` as ActiveTab,
    icon: ADDIN_ICONS[(a.config?.settings as Record<string, string>)?.icon] || ADDIN_ICONS.default,
    label: a.name,
  }))

  // Navigation items
  const navItems: { id: ActiveTab; icon: React.ReactNode; label: string }[] = [
    { id: 'search', icon: <Search size={18} />, label: 'Search' },
    { id: 'notes', icon: <StickyNote size={18} />, label: 'Notes' },
    { id: 'documents', icon: <FileText size={18} />, label: 'Documents' },
    { id: 'persona', icon: <Brain size={18} />, label: 'Persona' },
    { id: 'memory', icon: <BookOpen size={18} />, label: 'Memory' },
    { id: 'budget', icon: <Wallet size={18} />, label: 'Budget' },
    { id: 'schedule', icon: <CalendarDays size={18} />, label: 'Schedule' },
    { id: 'graph', icon: <GitBranch size={18} />, label: 'Knowledge Graph' },
    ...dynamicItems,
    { id: 'settings', icon: <Settings size={18} />, label: 'Settings' },
    { id: 'addins', icon: <Puzzle size={18} />, label: 'Add-ins' },
    { id: 'users', icon: <User size={18} />, label: 'Users' },
    { id: 'notifications', icon: <Bell size={18} />, label: 'Notifications' },
  ]

  return (
    <div className="h-full w-[280px] md:w-[260px] bg-dark-bg-tertiary flex flex-col border-r border-dark-border">
      {/* New Chat Button */}
      <div className="p-3">
        <button
          onClick={handleNewChat}
          className="w-full flex items-center gap-2 px-3 py-2.5 rounded-lg
                     bg-dark-accent-primary hover:bg-dark-accent-hover
                     text-white font-medium transition-colors"
        >
          <MessageSquarePlus size={18} />
          <span>New Chat</span>
        </button>
      </div>

      {/* Conversations Section */}
      <div className="flex-1 overflow-y-auto">
        <div className="px-3 py-2">
          <div className="flex items-center gap-2 px-2 py-1.5 text-dark-text-secondary text-sm">
            <MessageSquare size={16} />
            <span>Chats</span>
          </div>
          <ConversationList conversations={conversations} />
        </div>
      </div>

      {/* Navigation Items */}
      <div className="border-t border-dark-border p-2">
        {navItems.map((item) => (
          <button
            key={item.id}
            onClick={() => { setActiveTab(item.id); closeMobileSidebar() }}
            className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg
                       text-sm transition-colors
                       ${activeTab === item.id
                         ? 'bg-dark-bg-secondary text-dark-text-primary'
                         : 'text-dark-text-secondary hover:bg-dark-bg-secondary hover:text-dark-text-primary'
                       }`}
          >
            {item.icon}
            <span>{item.label}</span>
            {/* Unread badge for notifications */}
            {item.id === 'notifications' && unreadNotifs > 0 && (
              <span className="ml-auto bg-dark-accent-primary text-white text-[10px] font-bold px-1.5 py-0.5 rounded-full min-w-[18px] text-center">
                {unreadNotifs > 99 ? '99+' : unreadNotifs}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Donate button — hidden after user donates */}
      {!hasDonated && (
        <div className="px-3 pb-1">
          <a
            href="https://www.paypal.com/donate/?hosted_button_id=HAUBQZQAK7QJN"
            target="_blank"
            rel="noopener noreferrer"
            className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg
                       text-xs text-pink-400 hover:text-pink-300 hover:bg-pink-500/10
                       transition-colors"
          >
            <Heart size={13} fill="currentColor" />
            <span>Support Engram</span>
          </a>
        </div>
      )}

      {/* User Profile */}
      <div className="border-t border-dark-border p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-full bg-dark-accent-primary flex items-center justify-center">
              <User size={16} className="text-white" />
            </div>
            <span className="text-sm text-dark-text-primary truncate max-w-[100px]">
              {user?.name || 'User'}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={toggleTheme}
              className="p-1.5 rounded-lg text-dark-text-secondary hover:text-dark-text-primary
                         hover:bg-dark-bg-secondary transition-colors"
              title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
            </button>
            <button
              onClick={logout}
              className="text-xs text-dark-text-secondary hover:text-dark-text-primary px-1"
            >
              Logout
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
