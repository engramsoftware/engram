/**
 * UI state management using Zustand.
 * Handles sidebar, active tab, theme, and UI preferences.
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

/** Known built-in tabs. Dynamic addin tabs use 'addin:<id>' format. */
export type ActiveTab = 'chat' | 'search' | 'settings' | 'persona' | 'memory' | 'notes' | 'documents' | 'notifications' | 'graph' | 'budget' | 'schedule' | (string & {})
export type Theme = 'dark' | 'light'

/** Pages that moved into Settings: old tab id -> Settings section. */
const MOVED_TO_SETTINGS: Record<string, string> = { addins: 'addins', users: 'users' }

/** Settings sections that were renamed or merged (persisted ids from older versions). */
const RENAMED_SECTIONS: Record<string, string> = { performance: 'models', search: 'web', system: 'data' }

interface UIState {
  // Sidebar state
  sidebarOpen: boolean
  activeTab: ActiveTab
  theme: Theme
  /** Last opened Settings section (persisted so reload returns to it) */
  settingsSection: string
  /** Phones show the Settings section list first, then one section */
  settingsView: 'list' | 'section'
  /** Settings cards with unsaved typed changes, keyed by card id */
  dirtyCards: Record<string, true>
  /** Keyboard shortcuts overlay */
  showShortcuts: boolean

  // Actions
  toggleSidebar: () => void
  setSidebarOpen: (open: boolean) => void
  /** Switch page. Leaving Settings with unsaved changes asks first. */
  setActiveTab: (tab: ActiveTab) => void
  setSettingsSection: (section: string) => void
  setSettingsView: (view: 'list' | 'section') => void
  /** Jump to a Settings section from anywhere (deep links in other screens) */
  openSettings: (section: string) => void
  setCardDirty: (id: string, dirty: boolean) => void
  /**
   * Ask before an action that leaves Settings with unsaved changes (New Chat,
   * sign out, ...). Returns false if the user wants to stay.
   */
  requestLeave: () => boolean
  setShowShortcuts: (show: boolean | ((prev: boolean) => boolean)) => void
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
    (set, get) => ({
      sidebarOpen: true,
      activeTab: 'chat',
      theme: 'dark',
      settingsSection: 'models',
      settingsView: 'list',
      dirtyCards: {},
      showShortcuts: false,

      toggleSidebar: () => set((state) => ({
        sidebarOpen: !state.sidebarOpen
      })),

      setSidebarOpen: (open) => set({ sidebarOpen: open }),

      setActiveTab: (tab) => {
        const moved = MOVED_TO_SETTINGS[tab]
        if (moved) { get().openSettings(moved); return }
        const { activeTab } = get()
        if (activeTab === 'settings' && tab !== 'settings' && !get().requestLeave()) return
        // Opening Settings from elsewhere starts at the section list on phones
        set(tab === 'settings' && activeTab !== 'settings'
          ? { activeTab: tab, settingsView: 'list' }
          : { activeTab: tab })
      },

      setSettingsSection: (section) => set({ settingsSection: section }),

      setSettingsView: (view) => set({ settingsView: view }),

      openSettings: (section) => {
        const { activeTab } = get()
        if (activeTab !== 'settings' && Object.keys(get().dirtyCards).length > 0 && !get().requestLeave()) return
        set({ activeTab: 'settings', settingsSection: RENAMED_SECTIONS[section] ?? section, settingsView: 'section' })
      },

      setCardDirty: (id, dirty) => set((state) => {
        if (dirty === !!state.dirtyCards[id]) return state
        const next = { ...state.dirtyCards }
        if (dirty) next[id] = true
        else delete next[id]
        return { dirtyCards: next }
      }),

      requestLeave: () => {
        if (Object.keys(get().dirtyCards).length === 0) return true
        if (!window.confirm('You have unsaved changes in Settings. Discard them?')) return false
        set({ dirtyCards: {} })
        return true
      },

      setShowShortcuts: (show) => set((state) => ({
        showShortcuts: typeof show === 'function' ? show(state.showShortcuts) : show,
      })),

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
      version: 1,
      partialize: (state) => ({ theme: state.theme, settingsSection: state.settingsSection }),
      // v0 stored section ids that were later renamed or merged
      migrate: (persisted, version) => {
        const state = (persisted ?? {}) as { theme?: Theme; settingsSection?: string }
        if (version < 1 && state.settingsSection) {
          state.settingsSection = RENAMED_SECTIONS[state.settingsSection] ?? state.settingsSection
        }
        return state as UIState
      },
      onRehydrateStorage: () => (state) => {
        // Apply persisted theme on page load
        if (state?.theme) applyTheme(state.theme)
      },
    }
  )
)
