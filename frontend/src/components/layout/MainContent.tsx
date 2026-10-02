/**
 * Main content area that switches between tabs.
 * Renders chat interface or settings panels based on active tab.
 * On mobile, non-chat tabs get a header bar with back-to-chat and menu buttons;
 * inside a Settings section the back arrow returns to the Settings list.
 */

import { ArrowLeft, Menu } from 'lucide-react'
import { useUIStore } from '../../stores/uiStore'
import ChatInterface from '../chat/ChatInterface'
import SearchTab from '../search/SearchTab'
import SettingsTab, { SETTINGS_SECTIONS } from '../settings/SettingsTab'
import AddinPanelRouter from '../addins/panels/AddinPanelRouter'
import PersonaTab from '../persona/PersonaTab'
import MemoryTab from '../memory/MemoryTab'
import NotesTab from '../notes/NotesTab'
import DocumentsTab from '../documents/DocumentsTab'
import NotificationsTab from '../notifications/NotificationsTab'
import KnowledgeGraphTab from '../graph/KnowledgeGraphTab'
import BudgetTab from '../budget/BudgetTab'
import ScheduleTab from '../schedule/ScheduleTab'

/** Tab display names for the mobile header. */
const TAB_LABELS: Record<string, string> = {
  search: 'Search',
  settings: 'Settings',
  persona: 'Personas',
  memory: 'Memory',
  notes: 'Notes',
  documents: 'Documents',
  notifications: 'Notifications',
  graph: 'Knowledge Graph',
  budget: 'Budget',
  schedule: 'Schedule',
}

/** Get display label for a tab, including dynamic addin tabs. */
function getTabLabel(tab: string): string {
  if (tab.startsWith('addin:')) {
    const id = tab.slice(6)
    return id.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
  }
  return TAB_LABELS[tab] || 'Chat'
}

export default function MainContent() {
  const { activeTab, setActiveTab, toggleSidebar, sidebarOpen, settingsSection, settingsView, setSettingsView } = useUIStore()

  // Render content based on active tab
  const renderContent = () => {
    // Dynamic addin panels: tab IDs like 'addin:pomodoro', 'addin:mood_journal'
    if (typeof activeTab === 'string' && activeTab.startsWith('addin:')) {
      const addinId = activeTab.slice(6)
      const addinName = getTabLabel(activeTab)
      return <AddinPanelRouter addinId={addinId} addinName={addinName} />
    }

    switch (activeTab) {
      case 'chat':
        return <ChatInterface />
      case 'search':
        return <SearchTab />
      case 'settings':
        return <SettingsTab />
      case 'persona':
        return <PersonaTab />
      case 'memory':
        return <MemoryTab />
      case 'notes':
        return <NotesTab />
      case 'documents':
        return <DocumentsTab />
      case 'notifications':
        return <NotificationsTab />
      case 'graph':
        return <KnowledgeGraphTab />
      case 'budget':
        return <BudgetTab />
      case 'schedule':
        return <ScheduleTab />
      default:
        return <ChatInterface />
    }
  }

  const isNonChatTab = activeTab !== 'chat'
  // Phones open one Settings section at a time; back returns to the section list
  const inSettingsSection = activeTab === 'settings' && settingsView === 'section'
  const isPhone = () => window.matchMedia('(max-width: 767px)').matches
  const title = inSettingsSection && isPhone()
    ? SETTINGS_SECTIONS[settingsSection]?.label ?? 'Settings'
    : getTabLabel(activeTab)
  const goBack = () => {
    if (inSettingsSection && isPhone()) setSettingsView('list')
    else setActiveTab('chat')
  }

  return (
    <div className="flex-1 bg-dark-bg-primary overflow-hidden flex flex-col">
      {/* Header for non-chat tabs — back button + title + menu. Always on mobile;
          on desktop only while the sidebar is collapsed, so it can be reopened. */}
      {isNonChatTab && (
        <div className={`${sidebarOpen ? 'md:hidden' : ''} flex items-center gap-2 px-3 py-2.5 border-b border-dark-border
                        bg-dark-bg-primary/90 backdrop-blur-sm flex-shrink-0`}>
          <button
            onClick={goBack}
            className="p-1.5 rounded-lg text-dark-text-secondary hover:text-dark-text-primary
                       hover:bg-dark-bg-secondary transition-colors"
            aria-label={inSettingsSection && isPhone() ? 'Back to Settings' : 'Back to chat'}
          >
            <ArrowLeft size={20} />
          </button>
          <span className="text-sm font-semibold text-dark-text-primary flex-1">
            {title}
          </span>
          <button
            onClick={toggleSidebar}
            className="p-1.5 rounded-lg text-dark-text-secondary hover:text-dark-text-primary
                       hover:bg-dark-bg-secondary transition-colors"
            aria-label="Open menu"
          >
            <Menu size={20} />
          </button>
        </div>
      )}

      <div className="flex-1 overflow-hidden">
        {renderContent()}
      </div>
    </div>
  )
}
