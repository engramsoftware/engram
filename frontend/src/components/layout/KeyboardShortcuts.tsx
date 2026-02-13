/**
 * Global keyboard shortcuts handler.
 *
 * Registers document-level keydown listeners for common actions.
 * Renders nothing — this is a "headless" component mounted in Layout.
 *
 * Shortcuts:
 *   Ctrl+N / Cmd+N  — New conversation
 *   Ctrl+K / Cmd+K  — Focus search tab
 *   Ctrl+, / Cmd+,  — Open settings
 *   Ctrl+B / Cmd+B  — Toggle sidebar
 *   Ctrl+D / Cmd+D  — Toggle dark/light theme
 *   Escape           — Close sidebar on mobile / return to chat
 *   Ctrl+/ / Cmd+/  — Show shortcut help (toggles)
 */

import { useEffect, useState, useCallback } from 'react'
import { X, Keyboard } from 'lucide-react'
import { useUIStore } from '../../stores/uiStore'
import { useChatStore } from '../../stores/chatStore'
import { conversationsApi } from '../../services/api'

/** Detect macOS for displaying ⌘ vs Ctrl */
const isMac = navigator.platform.toUpperCase().includes('MAC')
const modKey = isMac ? '⌘' : 'Ctrl'

const SHORTCUTS = [
  { keys: `${modKey}+N`, description: 'New conversation' },
  { keys: `${modKey}+K`, description: 'Search' },
  { keys: `${modKey}+,`, description: 'Settings' },
  { keys: `${modKey}+B`, description: 'Toggle sidebar' },
  { keys: `${modKey}+D`, description: 'Toggle theme' },
  { keys: 'Escape', description: 'Back to chat' },
  { keys: `${modKey}+/`, description: 'Show shortcuts' },
]

export default function KeyboardShortcuts() {
  const [showHelp, setShowHelp] = useState(false)
  const { setActiveTab, toggleSidebar, setSidebarOpen, toggleTheme } = useUIStore()
  const { addConversation, setActiveConversation } = useChatStore()

  const handleNewChat = useCallback(async () => {
    try {
      const conv = await conversationsApi.create()
      addConversation(conv)
      setActiveConversation(conv.id)
      setActiveTab('chat')
    } catch (error) {
      console.error('Failed to create conversation:', error)
    }
  }, [addConversation, setActiveConversation, setActiveTab])

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const mod = isMac ? e.metaKey : e.ctrlKey

      // Don't intercept when typing in inputs (unless it's Escape)
      const target = e.target as HTMLElement
      const isInput = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable
      if (isInput && e.key !== 'Escape') return

      if (mod && e.key === 'n') {
        e.preventDefault()
        handleNewChat()
      } else if (mod && e.key === 'k') {
        e.preventDefault()
        setActiveTab('search')
      } else if (mod && e.key === ',') {
        e.preventDefault()
        setActiveTab('settings')
      } else if (mod && e.key === 'b') {
        e.preventDefault()
        toggleSidebar()
      } else if (mod && e.key === 'd') {
        e.preventDefault()
        toggleTheme()
      } else if (mod && e.key === '/') {
        e.preventDefault()
        setShowHelp(prev => !prev)
      } else if (e.key === 'Escape') {
        // Close help overlay first, then sidebar, then return to chat
        if (showHelp) {
          setShowHelp(false)
        } else if (window.innerWidth < 768) {
          setSidebarOpen(false)
        } else {
          setActiveTab('chat')
        }
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [handleNewChat, setActiveTab, toggleSidebar, setSidebarOpen, toggleTheme, showHelp])

  if (!showHelp) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
         onClick={() => setShowHelp(false)}>
      <div
        className="bg-dark-bg-secondary border border-dark-border rounded-xl shadow-2xl
                   w-full max-w-sm mx-4 overflow-hidden"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-dark-border">
          <div className="flex items-center gap-2">
            <Keyboard size={18} className="text-dark-accent-primary" />
            <h2 className="text-base font-semibold text-dark-text-primary">Keyboard Shortcuts</h2>
          </div>
          <button
            onClick={() => setShowHelp(false)}
            className="p-1 rounded-lg text-dark-text-secondary hover:text-dark-text-primary
                       hover:bg-dark-bg-primary transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Shortcuts list */}
        <div className="px-5 py-3 space-y-2">
          {SHORTCUTS.map(s => (
            <div key={s.keys} className="flex items-center justify-between py-1.5">
              <span className="text-sm text-dark-text-secondary">{s.description}</span>
              <kbd className="px-2 py-0.5 rounded bg-dark-bg-primary border border-dark-border
                             text-xs font-mono text-dark-text-primary">
                {s.keys}
              </kbd>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-dark-border">
          <p className="text-xs text-dark-text-secondary text-center">
            Press <kbd className="px-1 rounded bg-dark-bg-primary border border-dark-border text-[10px] font-mono">{modKey}+/</kbd> to toggle this panel
          </p>
        </div>
      </div>
    </div>
  )
}
