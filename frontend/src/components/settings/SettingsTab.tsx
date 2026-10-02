/**
 * Settings: sections in three groups (Assistant, You, Server).
 *
 * Desktop shows a grouped rail beside the open section. Phones show the
 * section list first (with a status per row) and open one section at a time;
 * the top bar's back arrow returns to the list. Every section stays mounted
 * while hidden, so unsaved input survives switching sections, and leaving
 * Settings with unsaved input asks first (see uiStore.requestLeave).
 */

import { useState, useEffect, useRef, type ReactNode } from 'react'
import {
  Settings, Cloud, Globe, Mail, Puzzle, UserCircle, Users, Database, ChevronRight,
} from 'lucide-react'
import { useAddinsStore } from '../../stores/addinsStore'
import { useAuthStore } from '../../stores/authStore'
import { useUIStore } from '../../stores/uiStore'
import { settingsApi } from '../../services/api'
import { friendlyModelName } from '../../utils/modelNames'
import { newChatModel, newChatProvider, providerName } from '../../utils/providers'
import type { LLMSettings } from '../../types/chat.types'
import ModelsSection from './ModelsSection'
import BraveSearchSettings from './BraveSearchSettings'
import Neo4jSettings from './Neo4jSettings'
import EmailSettings from './EmailSettings'
import AddinsSection from './AddinsSection'
import AccountSection from './AccountSection'
import UsersSection from './UsersSection'
import DataSection from './DataSection'
import { ActionButton, InfoNote, useIsPhone } from './primitives'

interface SectionMeta { label: string; icon: ReactNode; description: string }

export const SETTINGS_SECTIONS: Record<string, SectionMeta> = {
  models: { label: 'Models', icon: <Cloud size={16} />, description: 'The AI that answers you. One provider is in use at a time.' },
  web: { label: 'Web & knowledge', icon: <Globe size={16} />, description: 'Let Engram look things up and remember connections.' },
  email: { label: 'Email', icon: <Mail size={16} />, description: 'Engram can email you reminders, summaries and alerts.' },
  addins: { label: 'Add-ins', icon: <Puzzle size={16} />, description: 'Extra abilities for Engram.' },
  account: { label: 'Account', icon: <UserCircle size={16} />, description: 'Your profile, password, API tokens and how Engram looks.' },
  users: { label: 'Users', icon: <Users size={16} />, description: 'People who can sign in to this Engram. Only admins see this section.' },
  data: { label: 'Data & logs', icon: <Database size={16} />, description: 'Export or import your data, and server diagnostics.' },
}

const ALL_GROUPS: { label: string; ids: string[] }[] = [
  { label: 'Assistant', ids: ['models', 'web', 'email', 'addins'] },
  { label: 'You', ids: ['account'] },
  { label: 'Server', ids: ['users', 'data'] },
]
/** Sections only admins can open */
const ADMIN_ONLY = new Set(['users'])

export default function SettingsTab() {
  const [settings, setSettings] = useState<LLMSettings | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [retrying, setRetrying] = useState(false)
  const [userCount, setUserCount] = useState<number | null>(null)
  const { settingsSection, setSettingsSection, settingsView, setSettingsView, setActiveTab } = useUIStore()
  const isAdmin = useAuthStore(s => !!s.user?.is_admin)
  const GROUPS = ALL_GROUPS
    .map(g => ({ ...g, ids: g.ids.filter(id => isAdmin || !ADMIN_ONLY.has(id)) }))
    .filter(g => g.ids.length > 0)
  const ORDER = GROUPS.flatMap(g => g.ids)
  const section = ORDER.includes(settingsSection) ? settingsSection : 'models'
  const isPhone = useIsPhone()
  // A section is "active" (fetches, streams logs) only while it is on screen
  const showing = (id: string) => id === section && (settingsView === 'section' || !isPhone)
  const headingRefs = useRef<Record<string, HTMLHeadingElement | null>>({})
  const rowRefs = useRef<Record<string, HTMLButtonElement | null>>({})
  const userName = useAuthStore(s => s.user?.name)

  const refreshSettings = async () => {
    try {
      const data = await settingsApi.getLLMSettings()
      setSettings(data)
      setLoadError(false)
    } catch (error) {
      console.error('Failed to fetch settings:', error)
      setLoadError(true)
    }
  }

  useEffect(() => { refreshSettings().finally(() => setIsLoading(false)) }, [])

  // Retry in place: a full-page spinner would unmount the sections and lose drafts
  const retry = () => {
    setRetrying(true)
    refreshSettings().finally(() => setRetrying(false))
  }

  const { addins, loaded: addinsLoaded, fetchAddins } = useAddinsStore()
  useEffect(() => { if (!addinsLoaded) fetchAddins() }, [addinsLoaded, fetchAddins])
  const addinsOn = addins.filter(a => a.enabled).length
  const webSearchAddinOn = addins.some(a => a.internal_name === 'web_search' && a.enabled)

  const open = (id: string) => { setSettingsSection(id); setSettingsView('section') }

  // Phones swap the list and the section, so move focus with them: into the opened
  // section's heading, and back to its row when returning to the list
  const lastView = useRef(settingsView)
  useEffect(() => {
    if (!isPhone || lastView.current === settingsView) { lastView.current = settingsView; return }
    lastView.current = settingsView
    if (settingsView === 'section') headingRefs.current[section]?.focus()
    else rowRefs.current[section]?.focus()
  }, [settingsView, section, isPhone])

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-6 h-6 border-2 border-dark-accent-primary border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-dark-text-secondary">Loading settings…</p>
        </div>
      </div>
    )
  }

  // ---- Status shown in the header (desktop) and the section list (phones)
  const provider = newChatProvider(settings)
  const model = newChatModel(settings)
  const webOn = !!settings?.brave_search?.enabled
  const email = settings?.email
  const emailStatus = !email?.enabled ? 'Off' : email.password_set ? 'On' : 'Needs setup'
  const statusParts = settings ? [
    provider ? `New chats use ${providerName(provider)}${model ? ` · ${friendlyModelName(model)}` : ''}` : 'No AI provider set up',
    `Web search ${webOn ? 'on' : 'off'}`,
    `Email ${emailStatus.toLowerCase()}`,
    `${addinsOn} add-in${addinsOn !== 1 ? 's' : ''} on`,
  ] : []
  const rowStatus: Record<string, string> = {
    models: settings ? (provider ? providerName(provider) : 'Not set up') : '',
    web: settings ? `Search ${webOn ? 'on' : 'off'}` : '',
    email: settings ? emailStatus : '',
    addins: `${addinsOn} on`,
    account: userName ?? '',
    users: userCount !== null ? `${userCount} ${userCount === 1 ? 'person' : 'people'}` : '',
    data: '',
  }
  const description = (id: string) => {
    if (id === 'addins') return `${SETTINGS_SECTIONS.addins.description} ${addinsOn} of ${addins.length} on.`
    if (id === 'users' && userCount !== null) {
      return `${userCount} ${userCount === 1 ? 'person' : 'people'} can sign in to this Engram. Admins manage accounts; only admins see this section.`
    }
    return SETTINGS_SECTIONS[id].description
  }

  // Sections backed by GET /settings/llm. After a failed load they show only the
  // error (their forms would otherwise save defaults over the real values); after a
  // failed refresh they keep the last values under a warning. The other sections
  // don't use this request and keep working either way.
  const needsSettings = (body: (s: LLMSettings) => ReactNode) => (
    <div className="space-y-3">
      {loadError && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-500/30
                                     bg-red-500/10 px-4 py-3 text-xs text-red-400 [.light_&]:text-red-700">
          <span>{settings
            ? "Couldn't refresh your settings, so what you see may be out of date."
            : "Couldn't load your settings."}</span>
          <ActionButton onClick={retry} busy={retrying}>Retry</ActionButton>
        </div>
      )}
      {settings && body(settings)}
    </div>
  )

  const panels: Record<string, ReactNode> = {
    models: needsSettings(s => <ModelsSection settings={s} onUpdate={refreshSettings} />),
    web: needsSettings(s => (
      <div className="space-y-3">
        <BraveSearchSettings config={s.brave_search} onUpdate={refreshSettings} />
        <Neo4jSettings config={s.neo4j} onUpdate={refreshSettings} />
        {webSearchAddinOn && (
          <InfoNote>
            The Web Search add-in (Tavily or SerpAPI) is separate from Brave Search.{' '}
            <button type="button" onClick={() => open('addins')} className="text-dark-accent-text hover:underline">
              Manage it in Add-ins
            </button>
          </InfoNote>
        )}
      </div>
    )),
    email: needsSettings(s => (
      <div className="space-y-3">
        <button type="button" onClick={() => setActiveTab('notifications')}
                className="text-xs text-dark-accent-text hover:underline min-h-[40px] sm:min-h-0">
          View sent and scheduled emails ›
        </button>
        <EmailSettings config={s.email} onUpdate={refreshSettings} />
      </div>
    )),
    addins: <AddinsSection active={showing('addins')} />,
    account: <AccountSection />,
    users: <UsersSection active={showing('users')} onCount={setUserCount} />,
    data: <DataSection active={showing('data')} />,
  }

  const listView = settingsView === 'list'

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-4 md:py-8">
        {/* Header (desktop; phones show the title in the top bar) */}
        <div className="hidden md:flex items-center gap-3 mb-6">
          <div className="p-2 rounded-lg bg-dark-accent-primary/10">
            <Settings size={20} className="text-dark-accent-primary" />
          </div>
          <div className="min-w-0">
            <h1 className="text-xl font-semibold text-dark-text-primary">Settings</h1>
            {statusParts.length > 0 && <p className="text-sm text-dark-text-secondary">{statusParts.join(' · ')}</p>}
          </div>
        </div>

        <div className="md:flex md:items-start md:gap-8">
          {/* Desktop: grouped rail */}
          <nav aria-label="Settings sections" className="hidden md:block md:w-52 md:flex-shrink-0 md:sticky md:top-0 space-y-4">
            {GROUPS.map(g => (
              <div key={g.label} role="group" aria-labelledby={`settings-group-${g.label}`}>
                <p id={`settings-group-${g.label}`} className="px-3 mb-1 text-[10px] font-semibold uppercase tracking-wider text-dark-text-secondary">
                  {g.label}
                </p>
                {g.ids.map(id => {
                  const selected = id === section
                  return (
                    <button
                      key={id}
                      type="button"
                      aria-current={selected ? 'page' : undefined}
                      onClick={() => open(id)}
                      className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors
                                  focus:outline-none focus-visible:ring-2 focus-visible:ring-dark-accent-primary ${
                        selected
                          ? 'bg-dark-bg-secondary text-dark-text-primary font-medium'
                          : 'text-dark-text-secondary hover:bg-dark-bg-secondary hover:text-dark-text-primary'
                      }`}
                    >
                      {SETTINGS_SECTIONS[id].icon}
                      <span>{SETTINGS_SECTIONS[id].label}</span>
                    </button>
                  )
                })}
              </div>
            ))}
          </nav>

          {/* Phones: the section list comes first */}
          {listView && (
            <nav aria-label="Settings sections" className="md:hidden space-y-5">
              {statusParts.length > 0 && <p className="text-xs text-dark-text-secondary">{statusParts.join(' · ')}</p>}
              {GROUPS.map(g => (
                <div key={g.label} role="group" aria-labelledby={`settings-list-${g.label}`}>
                  <p id={`settings-list-${g.label}`} className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-dark-text-secondary">
                    {g.label}
                  </p>
                  <div className="rounded-lg border border-dark-border/60 bg-dark-bg-secondary/50 divide-y divide-dark-border/40">
                    {g.ids.map(id => (
                      <button
                        key={id}
                        ref={el => { rowRefs.current[id] = el }}
                        type="button"
                        onClick={() => open(id)}
                        className="w-full min-h-[48px] flex items-center gap-3 px-4 py-3 text-left text-sm text-dark-text-primary
                                   focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-dark-accent-primary"
                      >
                        <span className="text-dark-text-secondary">{SETTINGS_SECTIONS[id].icon}</span>
                        <span className="flex-1">{SETTINGS_SECTIONS[id].label}</span>
                        <span className="text-xs text-dark-text-secondary truncate max-w-[45%]">{rowStatus[id]}</span>
                        <ChevronRight size={16} className="text-dark-text-secondary flex-shrink-0" />
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </nav>
          )}

          {/* Sections stay mounted (hidden) so unsaved input survives switching */}
          <div className={`flex-1 min-w-0 max-w-3xl pb-12 ${listView ? 'hidden md:block' : ''}`}>
            {ORDER.map(id => (
              <section key={id} aria-labelledby={`settings-heading-${id}`} hidden={id !== section}>
                <div className="mb-4">
                  <h2 id={`settings-heading-${id}`} ref={el => { headingRefs.current[id] = el }} tabIndex={-1}
                      className="text-base font-semibold text-dark-text-primary focus:outline-none">
                    {SETTINGS_SECTIONS[id].label}
                  </h2>
                  <p className="text-xs text-dark-text-secondary mt-0.5">{description(id)}</p>
                </div>
                {panels[id]}
              </section>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
