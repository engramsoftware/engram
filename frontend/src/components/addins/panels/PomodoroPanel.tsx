/**
 * Pomodoro Timer panel.
 * Focus timer with work/break cycles, circular progress, and session tracking.
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { Play, Pause, RotateCcw, Coffee, Zap } from 'lucide-react'

type Phase = 'work' | 'break' | 'longBreak' | 'idle'

const PHASE_CONFIG: Record<Phase, { label: string; color: string; minutes: number }> = {
  work:      { label: 'Focus',       color: 'text-red-400',    minutes: 25 },
  break:     { label: 'Short Break', color: 'text-green-400',  minutes: 5 },
  longBreak: { label: 'Long Break',  color: 'text-blue-400',   minutes: 15 },
  idle:      { label: 'Ready',       color: 'text-dark-text-secondary', minutes: 25 },
}

export default function PomodoroPanel() {
  const [phase, setPhase] = useState<Phase>('idle')
  const [secondsLeft, setSecondsLeft] = useState(25 * 60)
  const [totalSeconds, setTotalSeconds] = useState(25 * 60)
  const [isRunning, setIsRunning] = useState(false)
  const [sessionsCompleted, setSessions] = useState(0)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const startPhase = useCallback((p: Phase) => {
    const mins = PHASE_CONFIG[p].minutes
    setPhase(p)
    setSecondsLeft(mins * 60)
    setTotalSeconds(mins * 60)
    setIsRunning(true)
  }, [])

  // Timer tick
  useEffect(() => {
    if (isRunning) {
      intervalRef.current = setInterval(() => {
        setSecondsLeft(prev => {
          if (prev <= 1) {
            setIsRunning(false)
            // Auto-transition
            if (phase === 'work') {
              setSessions(s => s + 1)
              // Play a subtle notification sound
              try { new Audio('data:audio/wav;base64,UklGRl9vT19teleVBQUUgABAAEARAAEACAABAAQABAA').play() } catch {}
            }
            return 0
          }
          return prev - 1
        })
      }, 1000)
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [isRunning, phase])

  // Format time as MM:SS
  const mins = Math.floor(secondsLeft / 60)
  const secs = secondsLeft % 60
  const timeDisplay = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`

  // Progress ring
  const progress = totalSeconds > 0 ? (1 - secondsLeft / totalSeconds) : 0
  const circumference = 2 * Math.PI * 90
  const dashOffset = circumference * (1 - progress)

  const config = PHASE_CONFIG[phase]

  return (
    <div className="h-full overflow-y-auto p-6 max-w-md mx-auto">
      <h1 className="text-2xl font-semibold text-dark-text-primary mb-6 text-center">
        Pomodoro Timer
      </h1>

      {/* Circular timer */}
      <div className="flex justify-center mb-8">
        <div className="relative w-56 h-56">
          <svg className="w-full h-full transform -rotate-90" viewBox="0 0 200 200">
            {/* Background ring */}
            <circle cx="100" cy="100" r="90" fill="none"
              stroke="currentColor" className="text-dark-border" strokeWidth="6" />
            {/* Progress ring */}
            <circle cx="100" cy="100" r="90" fill="none"
              stroke="currentColor" className={config.color} strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={dashOffset}
              style={{ transition: 'stroke-dashoffset 0.5s ease' }} />
          </svg>
          {/* Time display */}
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className={`text-4xl font-mono font-bold ${config.color}`}>
              {timeDisplay}
            </span>
            <span className="text-sm text-dark-text-secondary mt-1">{config.label}</span>
          </div>
        </div>
      </div>

      {/* Controls */}
      <div className="flex justify-center gap-3 mb-8">
        {phase === 'idle' || secondsLeft === 0 ? (
          <>
            <button
              onClick={() => startPhase('work')}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-red-500/20 text-red-400
                         hover:bg-red-500/30 border border-red-500/30 transition-colors"
            >
              <Zap size={16} /> Focus
            </button>
            <button
              onClick={() => startPhase('break')}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-green-500/20 text-green-400
                         hover:bg-green-500/30 border border-green-500/30 transition-colors"
            >
              <Coffee size={16} /> Break
            </button>
          </>
        ) : (
          <>
            <button
              onClick={() => setIsRunning(!isRunning)}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-dark-accent-primary/20
                         text-dark-accent-primary hover:bg-dark-accent-primary/30
                         border border-dark-accent-primary/30 transition-colors"
            >
              {isRunning ? <Pause size={16} /> : <Play size={16} />}
              {isRunning ? 'Pause' : 'Resume'}
            </button>
            <button
              onClick={() => { setIsRunning(false); setPhase('idle'); setSecondsLeft(25 * 60); setTotalSeconds(25 * 60) }}
              className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-dark-bg-secondary
                         text-dark-text-secondary hover:text-dark-text-primary
                         border border-dark-border transition-colors"
            >
              <RotateCcw size={16} /> Reset
            </button>
          </>
        )}
      </div>

      {/* Session counter */}
      <div className="text-center">
        <div className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-dark-bg-secondary border border-dark-border">
          <span className="text-sm text-dark-text-secondary">Sessions today:</span>
          <span className="text-lg font-bold text-dark-accent-primary">{sessionsCompleted}</span>
        </div>
      </div>

      {/* Quick tips */}
      <div className="mt-8 p-3 rounded-lg bg-dark-bg-secondary border border-dark-border">
        <p className="text-xs text-dark-text-secondary leading-relaxed">
          <strong className="text-dark-text-primary">How it works:</strong> Focus for 25 minutes,
          then take a 5-minute break. After 4 sessions, take a longer 15-minute break.
          The technique helps maintain deep focus while preventing burnout.
        </p>
      </div>
    </div>
  )
}
