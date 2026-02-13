/**
 * Mood Journal panel.
 * Quick mood/energy logging with emoji picker and history view.
 */

import { useState, useEffect } from 'react'

const MOODS = [
  { emoji: '😄', label: 'Great', value: 5 },
  { emoji: '🙂', label: 'Good', value: 4 },
  { emoji: '😐', label: 'Okay', value: 3 },
  { emoji: '😔', label: 'Low', value: 2 },
  { emoji: '😫', label: 'Bad', value: 1 },
]

const ENERGY = [
  { emoji: '⚡', label: 'High', value: 5 },
  { emoji: '🔋', label: 'Good', value: 4 },
  { emoji: '🔌', label: 'Medium', value: 3 },
  { emoji: '🪫', label: 'Low', value: 2 },
  { emoji: '😴', label: 'Drained', value: 1 },
]

interface MoodEntry {
  mood: number
  energy: number
  note: string
  timestamp: string
}

export default function MoodPanel() {
  const [selectedMood, setSelectedMood] = useState<number | null>(null)
  const [selectedEnergy, setSelectedEnergy] = useState<number | null>(null)
  const [note, setNote] = useState('')
  const [entries, setEntries] = useState<MoodEntry[]>([])
  const [saved, setSaved] = useState(false)

  // Load entries from localStorage
  useEffect(() => {
    try {
      const stored = localStorage.getItem('engram-mood-journal')
      if (stored) setEntries(JSON.parse(stored))
    } catch { /* ignore */ }
  }, [])

  const saveEntry = () => {
    if (selectedMood === null || selectedEnergy === null) return

    const entry: MoodEntry = {
      mood: selectedMood,
      energy: selectedEnergy,
      note,
      timestamp: new Date().toISOString(),
    }

    const updated = [entry, ...entries].slice(0, 50) // keep last 50
    setEntries(updated)
    localStorage.setItem('engram-mood-journal', JSON.stringify(updated))

    // Reset
    setSelectedMood(null)
    setSelectedEnergy(null)
    setNote('')
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  const getMoodEmoji = (val: number) => MOODS.find(m => m.value === val)?.emoji || '?'
  const getEnergyEmoji = (val: number) => ENERGY.find(e => e.value === val)?.emoji || '?'

  // Today's entries
  const today = new Date().toDateString()
  const todayEntries = entries.filter(e => new Date(e.timestamp).toDateString() === today)

  return (
    <div className="h-full overflow-y-auto p-6 max-w-md mx-auto">
      <h1 className="text-2xl font-semibold text-dark-text-primary mb-6 text-center">
        Mood Journal
      </h1>

      {/* Mood picker */}
      <div className="mb-5">
        <h3 className="text-sm font-medium text-dark-text-secondary mb-3">How are you feeling?</h3>
        <div className="flex justify-center gap-2">
          {MOODS.map(m => (
            <button
              key={m.value}
              onClick={() => setSelectedMood(m.value)}
              className={`flex flex-col items-center gap-1 p-3 rounded-xl transition-all
                ${selectedMood === m.value
                  ? 'bg-dark-accent-primary/20 border-dark-accent-primary/50 scale-110'
                  : 'bg-dark-bg-secondary border-dark-border hover:bg-dark-bg-secondary/80'}
                border`}
            >
              <span className="text-2xl">{m.emoji}</span>
              <span className="text-[10px] text-dark-text-secondary">{m.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Energy picker */}
      <div className="mb-5">
        <h3 className="text-sm font-medium text-dark-text-secondary mb-3">Energy level?</h3>
        <div className="flex justify-center gap-2">
          {ENERGY.map(e => (
            <button
              key={e.value}
              onClick={() => setSelectedEnergy(e.value)}
              className={`flex flex-col items-center gap-1 p-3 rounded-xl transition-all
                ${selectedEnergy === e.value
                  ? 'bg-dark-accent-primary/20 border-dark-accent-primary/50 scale-110'
                  : 'bg-dark-bg-secondary border-dark-border hover:bg-dark-bg-secondary/80'}
                border`}
            >
              <span className="text-2xl">{e.emoji}</span>
              <span className="text-[10px] text-dark-text-secondary">{e.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Optional note */}
      <div className="mb-5">
        <textarea
          value={note}
          onChange={e => setNote(e.target.value)}
          placeholder="Add a quick note (optional)..."
          rows={2}
          className="w-full px-3 py-2 rounded-lg bg-dark-bg-secondary border border-dark-border
                     text-sm text-dark-text-primary placeholder-dark-text-secondary/50
                     focus:outline-none focus:border-dark-accent-primary/50 resize-none"
        />
      </div>

      {/* Save button */}
      <div className="flex justify-center mb-8">
        <button
          onClick={saveEntry}
          disabled={selectedMood === null || selectedEnergy === null}
          className="px-6 py-2.5 rounded-lg bg-dark-accent-primary hover:bg-dark-accent-primary/80
                     text-white font-medium text-sm disabled:opacity-30 disabled:cursor-not-allowed
                     transition-colors"
        >
          {saved ? '✓ Saved!' : 'Log Mood'}
        </button>
      </div>

      {/* Today's history */}
      {todayEntries.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-dark-text-secondary mb-3">
            Today ({todayEntries.length} {todayEntries.length === 1 ? 'entry' : 'entries'})
          </h3>
          <div className="space-y-2">
            {todayEntries.map((entry, i) => (
              <div key={i} className="flex items-center gap-3 p-3 rounded-lg bg-dark-bg-secondary border border-dark-border">
                <span className="text-xl">{getMoodEmoji(entry.mood)}</span>
                <span className="text-xl">{getEnergyEmoji(entry.energy)}</span>
                <div className="flex-1 min-w-0">
                  {entry.note && (
                    <p className="text-xs text-dark-text-primary truncate">{entry.note}</p>
                  )}
                  <p className="text-[10px] text-dark-text-secondary">
                    {new Date(entry.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Info */}
      <div className="mt-6 p-3 rounded-lg bg-dark-bg-secondary border border-dark-border">
        <p className="text-xs text-dark-text-secondary leading-relaxed">
          <strong className="text-dark-text-primary">Track your patterns:</strong> Log your mood
          throughout the day to spot trends. Your entries are stored locally and can help
          the AI understand your context better.
        </p>
      </div>
    </div>
  )
}
