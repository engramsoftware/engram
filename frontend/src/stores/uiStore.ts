/**
 * UI state management using Zustand.
 * Handles sidebar, active tab, theme, and UI preferences.
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/** Known built-in tabs. Dynamic addin tabs use 'addin:<id>' format. */
export type ActiveTab = 'chat' | 'search' | 'settings' | 'addins' | 'persona' | 'memory' | 'notes' | 'documents' | 'users' | 'notifications' | 'graph' | 'budget' | 'schedule' | (string & {})
export type Theme = 'dark' | 'light'

interface UIState {
  // Sidebar state
  sidebarOpen: boolean
  activeTab: ActiveTab
  theme: Theme

  // Actions
  toggleSidebar: () => void
  setSidebarOpen: (open: boolean) => void
  setActiveTab: (tab: ActiveTab) => void
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
}

/** Apply theme class to <html> element so CSS variables switch. */
function applyTheme(theme: Theme) {
  if (theme === 'light') {
    document.documentElement.classList.add('light')
  } else {
    document.documentElement.classList.remove('light')
  }
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      sidebarOpen: true,
      activeTab: 'chat',
      theme: 'dark',

      toggleSidebar: () => set((state) => ({
        sidebarOpen: !state.sidebarOpen
      })),

      setSidebarOpen: (open) => set({ sidebarOpen: open }),

      setActiveTab: (tab) => set({ activeTab: tab }),

      setTheme: (theme) => {
        applyTheme(theme)
        set({ theme })
      },

      toggleTheme: () => set((state) => {
        const next = state.theme === 'dark' ? 'light' : 'dark'
        applyTheme(next)
        return { theme: next }
      }),
    }),
    {
      name: 'ui-storage',
      partialize: (state) => ({ theme: state.theme }),
      onRehydrateStorage: () => (state) => {
        // Apply persisted theme on page load
        if (state?.theme) applyTheme(state.theme)
      },
    }
  )
)
