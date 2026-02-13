/**
 * Schedule tab — shared calendar with event management.
 *
 * Events are shared between all users (family/team calendar).
 * Supports manual creation, LLM-added events, and Gmail imports.
 * Shows a week/month view with category color coding.
 */

import { useEffect, useState, useCallback } from 'react'
import {
  CalendarDays,
  Plus,
  ChevronLeft,
  ChevronRight,
  Clock,
  MapPin,
  Repeat,
  Trash2,
  Mail,
  Bot,
  User,
  X,
} from 'lucide-react'
// Auth store available if needed for user-specific features

// ── Types ──────────────────────────────────────────────────────

interface ScheduleEvent {
  id: string
  title: string
  start_time: string
  end_time: string | null
  description: string
  location: string
  category: string
  recurring: string | null
  all_day: boolean
  source: string
  created_by: string
  created_at: string
}

// ── API — uses centralized fetchWithAuth (Zustand auth token) ──
import { scheduleApi } from '../../services/api'

// ── Helpers ────────────────────────────────────────────────────

const CATEGORY_COLORS: Record<string, string> = {
  general: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  appointment: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  reminder: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  task: 'bg-green-500/20 text-green-400 border-green-500/30',
  meeting: 'bg-red-500/20 text-red-400 border-red-500/30',
  social: 'bg-pink-500/20 text-pink-400 border-pink-500/30',
  health: 'bg-teal-500/20 text-teal-400 border-teal-500/30',
}

function getCategoryStyle(cat: string): string {
  return CATEGORY_COLORS[cat] || CATEGORY_COLORS.general
}

function sourceIcon(source: string) {
  if (source === 'gmail') return <Mail size={12} />
  if (source === 'llm') return <Bot size={12} />
  return <User size={12} />
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })
}

function getWeekDates(date: Date): Date[] {
  const start = new Date(date)
  start.setDate(start.getDate() - start.getDay())
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(start)
    d.setDate(d.getDate() + i)
    return d
  })
}

function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
}

// ── Component ──────────────────────────────────────────────────

export default function ScheduleTab() {
  const [events, setEvents] = useState<ScheduleEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [currentDate, setCurrentDate] = useState(new Date())
  const [showForm, setShowForm] = useState(false)

  // Form state
  const [formTitle, setFormTitle] = useState('')
  const [formDate, setFormDate] = useState('')
  const [formTime, setFormTime] = useState('')
  const [formEndTime, setFormEndTime] = useState('')
  const [formDescription, setFormDescription] = useState('')
  const [formLocation, setFormLocation] = useState('')
  const [formCategory, setFormCategory] = useState('general')
  const [formRecurring, setFormRecurring] = useState('')
  const [formAllDay, setFormAllDay] = useState(false)

  const weekDates = getWeekDates(currentDate)
  const today = new Date()

  const loadEvents = useCallback(async () => {
    try {
      setLoading(true)
      const start = weekDates[0].toISOString().split('T')[0]
      const endDate = new Date(weekDates[6])
      endDate.setDate(endDate.getDate() + 1)
      const end = endDate.toISOString().split('T')[0]
      const data = await scheduleApi.list(start, end)
      setEvents(data)
    } catch (err) {
      console.error('Failed to load events:', err)
    } finally {
      setLoading(false)
    }
  }, [currentDate])

  useEffect(() => {
    loadEvents()
  }, [loadEvents])

  function prevWeek() {
    const d = new Date(currentDate)
    d.setDate(d.getDate() - 7)
    setCurrentDate(d)
  }

  function nextWeek() {
    const d = new Date(currentDate)
    d.setDate(d.getDate() + 7)
    setCurrentDate(d)
  }

  function goToday() {
    setCurrentDate(new Date())
  }

  function openFormForDay(day: Date) {
    setFormDate(day.toISOString().split('T')[0])
    setFormTime('09:00')
    setFormEndTime('10:00')
    setFormTitle('')
    setFormDescription('')
    setFormLocation('')
    setFormCategory('general')
    setFormRecurring('')
    setFormAllDay(false)
    setShowForm(true)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!formTitle.trim() || !formDate) return

    const startTime = formAllDay
      ? `${formDate}T00:00`
      : `${formDate}T${formTime || '00:00'}`
    const endTime = formAllDay
      ? undefined
      : formEndTime ? `${formDate}T${formEndTime}` : undefined

    try {
      await scheduleApi.create({
        title: formTitle.trim(),
        start_time: startTime,
        end_time: endTime,
        description: formDescription,
        location: formLocation,
        category: formCategory,
        recurring: formRecurring || undefined,
        all_day: formAllDay,
        source: 'manual',
      })
      setShowForm(false)
      loadEvents()
    } catch (err) {
      console.error('Failed to create event:', err)
    }
  }

  async function handleDelete(id: string) {
    try {
      await scheduleApi.delete(id)
      loadEvents()
    } catch (err) {
      console.error('Failed to delete event:', err)
    }
  }

  function getEventsForDay(day: Date): ScheduleEvent[] {
    return events.filter((ev) => {
      const evDate = new Date(ev.start_time)
      return isSameDay(evDate, day)
    })
  }

  const weekLabel = `${weekDates[0].toLocaleDateString([], { month: 'short', day: 'numeric' })} – ${weekDates[6].toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })}`

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-dark-border">
        <div className="flex items-center gap-3">
          <CalendarDays size={24} className="text-dark-accent-primary" />
          <div>
            <h1 className="text-lg font-semibold text-dark-text-primary">Schedule</h1>
            <p className="text-xs text-dark-text-secondary">Shared calendar — all users</p>
          </div>
        </div>
        <button
          onClick={() => openFormForDay(today)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-dark-accent-primary
                     hover:bg-dark-accent-hover text-white text-sm transition-colors"
        >
          <Plus size={16} />
          Add Event
        </button>
      </div>

      {/* Week Navigation */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-dark-border/50">
        <button onClick={prevWeek} className="p-1.5 rounded hover:bg-dark-bg-secondary text-dark-text-secondary">
          <ChevronLeft size={18} />
        </button>
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-dark-text-primary">{weekLabel}</span>
          <button
            onClick={goToday}
            className="text-xs px-2 py-0.5 rounded bg-dark-bg-secondary text-dark-text-secondary
                       hover:text-dark-text-primary transition-colors"
          >
            Today
          </button>
        </div>
        <button onClick={nextWeek} className="p-1.5 rounded hover:bg-dark-bg-secondary text-dark-text-secondary">
          <ChevronRight size={18} />
        </button>
      </div>

      {/* Week Grid */}
      <div className="flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="flex items-center justify-center h-32 text-dark-text-secondary">
            Loading...
          </div>
        ) : (
          <div className="grid grid-cols-7 gap-2">
            {weekDates.map((day) => {
              const dayEvents = getEventsForDay(day)
              const isToday = isSameDay(day, today)
              return (
                <div
                  key={day.toISOString()}
                  className={`min-h-[140px] rounded-lg border p-2 cursor-pointer transition-colors
                    ${isToday
                      ? 'border-dark-accent-primary/50 bg-dark-accent-primary/5'
                      : 'border-dark-border/30 hover:border-dark-border'
                    }`}
                  onClick={() => openFormForDay(day)}
                >
                  {/* Day header */}
                  <div className="flex items-center justify-between mb-1.5">
                    <span className={`text-xs font-medium ${isToday ? 'text-dark-accent-primary' : 'text-dark-text-secondary'}`}>
                      {day.toLocaleDateString([], { weekday: 'short' })}
                    </span>
                    <span className={`text-sm font-semibold ${isToday
                      ? 'bg-dark-accent-primary text-white w-6 h-6 rounded-full flex items-center justify-center'
                      : 'text-dark-text-primary'
                    }`}>
                      {day.getDate()}
                    </span>
                  </div>

                  {/* Events for this day */}
                  <div className="space-y-1">
                    {dayEvents.map((ev) => (
                      <div
                        key={ev.id}
                        className={`text-[10px] px-1.5 py-1 rounded border ${getCategoryStyle(ev.category)} group relative`}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className="flex items-center gap-1">
                          {sourceIcon(ev.source)}
                          <span className="font-medium truncate">{ev.title}</span>
                        </div>
                        {!ev.all_day && (
                          <div className="flex items-center gap-0.5 opacity-70">
                            <Clock size={8} />
                            <span>{formatTime(ev.start_time)}</span>
                          </div>
                        )}
                        {/* Delete button on hover */}
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            handleDelete(ev.id)
                          }}
                          className="absolute top-0.5 right-0.5 hidden group-hover:block
                                     p-0.5 rounded bg-red-500/20 text-red-400 hover:bg-red-500/40"
                        >
                          <Trash2 size={10} />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* Upcoming Events List (below the week grid) */}
        <div className="mt-4">
          <h2 className="text-sm font-medium text-dark-text-secondary mb-2">This Week's Events</h2>
          {events.length === 0 ? (
            <p className="text-xs text-dark-text-secondary">No events this week. Click a day or "Add Event" to create one.</p>
          ) : (
            <div className="space-y-2">
              {events
                .sort((a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime())
                .map((ev) => (
                  <div
                    key={ev.id}
                    className={`flex items-start gap-3 p-3 rounded-lg border ${getCategoryStyle(ev.category)}`}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        {sourceIcon(ev.source)}
                        <span className="font-medium text-sm">{ev.title}</span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-dark-bg-secondary">
                          {ev.category}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 mt-1 text-xs opacity-70">
                        <span className="flex items-center gap-1">
                          <CalendarDays size={11} />
                          {formatDate(ev.start_time)}
                        </span>
                        {!ev.all_day && (
                          <span className="flex items-center gap-1">
                            <Clock size={11} />
                            {formatTime(ev.start_time)}
                            {ev.end_time && ` – ${formatTime(ev.end_time)}`}
                          </span>
                        )}
                        {ev.location && (
                          <span className="flex items-center gap-1">
                            <MapPin size={11} />
                            {ev.location}
                          </span>
                        )}
                        {ev.recurring && (
                          <span className="flex items-center gap-1">
                            <Repeat size={11} />
                            {ev.recurring}
                          </span>
                        )}
                      </div>
                      {ev.description && (
                        <p className="text-xs mt-1 opacity-60">{ev.description}</p>
                      )}
                    </div>
                    <button
                      onClick={() => handleDelete(ev.id)}
                      className="p-1 rounded hover:bg-red-500/20 text-red-400/50 hover:text-red-400"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
            </div>
          )}
        </div>
      </div>

      {/* Add Event Modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-dark-bg-secondary rounded-xl border border-dark-border w-full max-w-md p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-dark-text-primary">New Event</h2>
              <button onClick={() => setShowForm(false)} className="text-dark-text-secondary hover:text-dark-text-primary">
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-3">
              <input
                type="text"
                placeholder="Event title"
                value={formTitle}
                onChange={(e) => setFormTitle(e.target.value)}
                className="w-full px-3 py-2 rounded-lg bg-dark-bg-primary border border-dark-border
                           text-dark-text-primary text-sm focus:border-dark-accent-primary outline-none"
                autoFocus
                required
              />

              <div className="flex gap-2">
                <input
                  type="date"
                  value={formDate}
                  onChange={(e) => setFormDate(e.target.value)}
                  className="flex-1 px-3 py-2 rounded-lg bg-dark-bg-primary border border-dark-border
                             text-dark-text-primary text-sm focus:border-dark-accent-primary outline-none"
                  required
                />
                <label className="flex items-center gap-1.5 text-xs text-dark-text-secondary">
                  <input
                    type="checkbox"
                    checked={formAllDay}
                    onChange={(e) => setFormAllDay(e.target.checked)}
                    className="rounded"
                  />
                  All day
                </label>
              </div>

              {!formAllDay && (
                <div className="flex gap-2">
                  <div className="flex-1">
                    <label className="text-xs text-dark-text-secondary mb-1 block">Start</label>
                    <input
                      type="time"
                      value={formTime}
                      onChange={(e) => setFormTime(e.target.value)}
                      className="w-full px-3 py-2 rounded-lg bg-dark-bg-primary border border-dark-border
                                 text-dark-text-primary text-sm focus:border-dark-accent-primary outline-none"
                    />
                  </div>
                  <div className="flex-1">
                    <label className="text-xs text-dark-text-secondary mb-1 block">End</label>
                    <input
                      type="time"
                      value={formEndTime}
                      onChange={(e) => setFormEndTime(e.target.value)}
                      className="w-full px-3 py-2 rounded-lg bg-dark-bg-primary border border-dark-border
                                 text-dark-text-primary text-sm focus:border-dark-accent-primary outline-none"
                    />
                  </div>
                </div>
              )}

              <input
                type="text"
                placeholder="Location (optional)"
                value={formLocation}
                onChange={(e) => setFormLocation(e.target.value)}
                className="w-full px-3 py-2 rounded-lg bg-dark-bg-primary border border-dark-border
                           text-dark-text-primary text-sm focus:border-dark-accent-primary outline-none"
              />

              <textarea
                placeholder="Description (optional)"
                value={formDescription}
                onChange={(e) => setFormDescription(e.target.value)}
                rows={2}
                className="w-full px-3 py-2 rounded-lg bg-dark-bg-primary border border-dark-border
                           text-dark-text-primary text-sm focus:border-dark-accent-primary outline-none resize-none"
              />

              <div className="flex gap-2">
                <select
                  value={formCategory}
                  onChange={(e) => setFormCategory(e.target.value)}
                  className="flex-1 px-3 py-2 rounded-lg bg-dark-bg-primary border border-dark-border
                             text-dark-text-primary text-sm focus:border-dark-accent-primary outline-none"
                >
                  <option value="general">General</option>
                  <option value="appointment">Appointment</option>
                  <option value="meeting">Meeting</option>
                  <option value="reminder">Reminder</option>
                  <option value="task">Task</option>
                  <option value="social">Social</option>
                  <option value="health">Health</option>
                </select>

                <select
                  value={formRecurring}
                  onChange={(e) => setFormRecurring(e.target.value)}
                  className="flex-1 px-3 py-2 rounded-lg bg-dark-bg-primary border border-dark-border
                             text-dark-text-primary text-sm focus:border-dark-accent-primary outline-none"
                >
                  <option value="">No repeat</option>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                  <option value="monthly">Monthly</option>
                </select>
              </div>

              <button
                type="submit"
                className="w-full py-2 rounded-lg bg-dark-accent-primary hover:bg-dark-accent-hover
                           text-white text-sm font-medium transition-colors"
              >
                Create Event
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
