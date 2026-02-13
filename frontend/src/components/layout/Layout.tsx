/**
 * Main layout component with sidebar and content area.
 * Desktop (md+): sidebar is a fixed inline panel that slides in/out.
 * Mobile (<md): sidebar is a slide-over overlay with backdrop dismiss.
 */

import { useEffect } from 'react'
import { Menu } from 'lucide-react'
import Sidebar from './Sidebar'
import MainContent from './MainContent'
import KeyboardShortcuts from './KeyboardShortcuts'
import DonationPopup from '../DonationPopup'
import { useUIStore } from '../../stores/uiStore'

export default function Layout() {
  const { sidebarOpen, setSidebarOpen, toggleSidebar } = useUIStore()

  // On mobile, sidebar should start closed
  useEffect(() => {
    if (window.innerWidth < 768) {
      setSidebarOpen(false)
    }
  }, [setSidebarOpen])

  return (
    <div className="flex h-screen bg-dark-bg-primary">
      {/* ── Desktop sidebar (inline, not overlay) ── */}
      <div
        className={`hidden md:block transition-all duration-300 overflow-hidden flex-shrink-0
                    ${sidebarOpen ? 'w-[260px]' : 'w-0'}`}
      >
        <Sidebar />
      </div>

      {/* ── Mobile sidebar (overlay + backdrop) ── */}
      {/* Backdrop */}
      {sidebarOpen && (
        <div
          className="md:hidden fixed inset-0 bg-black/50 z-30"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      {/* Slide-over panel */}
      <div
        className={`md:hidden fixed top-0 left-0 z-40 h-full w-[280px]
                    transform transition-transform duration-300 ease-in-out
                    ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}
      >
        <Sidebar />
      </div>

      {/* ── Main content ── */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        {/* Mobile hamburger — shown when sidebar is closed */}
        {!sidebarOpen && (
          <button
            onClick={toggleSidebar}
            className="md:hidden fixed top-3 left-3 z-20 p-2 rounded-lg
                       bg-dark-bg-secondary/90 backdrop-blur-sm border border-dark-border
                       text-dark-text-secondary hover:text-dark-text-primary
                       transition-colors"
            aria-label="Open menu"
          >
            <Menu size={20} />
          </button>
        )}
        <MainContent />
      </div>

      {/* Global keyboard shortcuts (renders nothing unless help overlay is open) */}
      <KeyboardShortcuts />

      {/* Donation popup (shows every 15 messages if not donated) */}
      <DonationPopup />
    </div>
  )
}
