/**
 * Main layout component with sidebar and content area.
 * One Sidebar instance serves both layouts:
 * Desktop (md+): an inline column that collapses to zero width.
 * Mobile (<md): a slide-over drawer with a backdrop.
 * The menu button that reopens it lives in the chat / tab headers.
 */

import { useEffect } from 'react'
import Sidebar from './Sidebar'
import MainContent from './MainContent'
import KeyboardShortcuts from './KeyboardShortcuts'
import DonationPopup from '../DonationPopup'
import { useUIStore } from '../../stores/uiStore'

export default function Layout() {
  const { sidebarOpen, setSidebarOpen } = useUIStore()

  // On mobile, sidebar should start closed
  useEffect(() => {
    if (window.innerWidth < 768) {
      setSidebarOpen(false)
    }
  }, [setSidebarOpen])

  return (
    <div className="flex h-screen supports-[height:100dvh]:h-dvh bg-dark-bg-primary">
      {/* Backdrop (mobile only) — kept mounted so it can fade in and out */}
      <div
        className={`md:hidden fixed inset-0 bg-black/50 z-30 transition-opacity duration-300
                    ${sidebarOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
        onClick={() => setSidebarOpen(false)}
        aria-hidden="true"
      />

      {/* Sidebar. `invisible` when closed keeps its off-screen links out of the tab
          order; visibility is transitioned so it only flips once the slide ends. */}
      <div
        className={`fixed inset-y-0 left-0 z-40 w-[280px] ease-in-out duration-300
                    transition-[transform,visibility]
                    md:static md:z-auto md:translate-x-0 md:overflow-hidden md:flex-shrink-0
                    md:transition-[width,visibility]
                    ${sidebarOpen
                      ? 'translate-x-0 visible md:w-[260px]'
                      : '-translate-x-full invisible md:w-0'}`}
      >
        <Sidebar />
      </div>

      {/* ── Main content ── */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        <MainContent />
      </div>

      {/* Global keyboard shortcuts (renders nothing unless help overlay is open) */}
      <KeyboardShortcuts />

      {/* Donation popup (shows every 15 messages if not donated) */}
      <DonationPopup />
    </div>
  )
}
