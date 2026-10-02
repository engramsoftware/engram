/**
 * Shared building blocks for the Settings screen.
 *
 * Every settings card used to hand-roll its own header, toggle and save
 * feedback; these keep them consistent and accessible:
 * - Switch: a labelled role="switch" button
 * - SettingsCard: expandable card whose header is a real button; the enable
 *   switch sits beside the header instead of inside it
 * - TextField: input with an associated label
 * - useAction + ActionStatus: run a save/test call and show the outcome,
 *   including failures (these were only logged to the console before)
 */

import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { Check, ChevronDown, ChevronRight, Loader2, X } from 'lucide-react'

// ------------------------------------------------------------------ Switch

interface SwitchProps {
  checked: boolean
  onChange: (next: boolean) => void
  label: string
  disabled?: boolean
  size?: 'sm' | 'md'
}

/** Accessible on/off switch. */
export function Switch({ checked, onChange, label, disabled = false, size = 'md' }: SwitchProps) {
  const sm = size === 'sm'
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex items-center flex-shrink-0 rounded-full transition-colors
                  ${sm ? 'w-9 h-5' : 'w-10 h-6'}
                  ${checked ? 'bg-dark-accent-primary' : 'bg-dark-border ring-1 ring-inset ring-dark-text-secondary/70'}
                  disabled:opacity-50 focus:outline-none focus-visible:ring-2
                  focus-visible:ring-dark-accent-primary focus-visible:ring-offset-2
                  focus-visible:ring-offset-dark-bg-primary`}
    >
      <span
        className={`inline-block rounded-full bg-white shadow-sm transition-transform
                    ${sm ? 'w-3.5 h-3.5' : 'w-4 h-4'}
                    ${checked ? (sm ? 'translate-x-[18px]' : 'translate-x-5') : (sm ? 'translate-x-[3px]' : 'translate-x-1')}`}
      />
    </button>
  )
}

// ------------------------------------------------------------------ Badge

const BADGE_TONES = {
  green: 'text-green-400 bg-green-400/10 [.light_&]:text-green-700 [.light_&]:bg-green-600/10',
  blue: 'text-blue-400 bg-blue-400/10 [.light_&]:text-blue-700 [.light_&]:bg-blue-600/10',
  yellow: 'text-yellow-400 bg-yellow-400/10 [.light_&]:text-yellow-800 [.light_&]:bg-yellow-500/15',
  gray: 'text-dark-text-secondary bg-dark-bg-primary',
} as const

export function Badge({ tone = 'gray', children }: { tone?: keyof typeof BADGE_TONES; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full ${BADGE_TONES[tone]}`}>
      {children}
    </span>
  )
}

// ------------------------------------------------------------------ SettingsCard

interface SettingsCardProps {
  title: string
  subtitle?: string
  icon?: ReactNode
  /** Badges shown next to the title. */
  badges?: ReactNode
  /** Extra content between the header and the switch (e.g. a model count). */
  aside?: ReactNode
  /** When set, renders an enable switch and highlights the card while enabled. */
  enabled?: boolean
  onToggle?: (next: boolean) => void
  toggleDisabled?: boolean
  defaultOpen?: boolean
  /** Controlled open state (optional). */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** Keep the body mounted (hidden) while collapsed, so its state survives. */
  keepMounted?: boolean
  children: ReactNode
}

export function SettingsCard({
  title, subtitle, icon, badges, aside, enabled, onToggle, toggleDisabled,
  defaultOpen = false, open: openProp, onOpenChange, keepMounted = false, children,
}: SettingsCardProps) {
  const [openState, setOpenState] = useState(defaultOpen)
  const open = openProp ?? openState
  const setOpen = (next: boolean) => { if (openProp === undefined) setOpenState(next); onOpenChange?.(next) }
  const bodyId = useId()

  return (
    <div className={`rounded-lg border transition-colors ${
      enabled ? 'bg-dark-bg-secondary border-dark-accent-primary/30' : 'bg-dark-bg-secondary/50 border-dark-border/60'
    }`}>
      <div className="flex items-center gap-3 pr-4">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-controls={bodyId}
          className="flex-1 min-w-0 flex items-center gap-3 pl-4 py-3 text-left rounded-lg
                     focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-dark-accent-primary"
        >
          {open
            ? <ChevronDown size={14} className="text-dark-text-secondary flex-shrink-0" />
            : <ChevronRight size={14} className="text-dark-text-secondary flex-shrink-0" />}
          {icon && <span className="text-dark-text-secondary flex-shrink-0">{icon}</span>}
          <span className="flex-1 min-w-0">
            <span className="flex items-center gap-2 flex-wrap">
              <span className={`text-sm font-medium ${enabled === false ? 'text-dark-text-secondary' : 'text-dark-text-primary'}`}>
                {title}
              </span>
              {badges}
            </span>
            {subtitle && <span className="block text-xs text-dark-text-secondary truncate">{subtitle}</span>}
          </span>
        </button>
        {aside}
        {onToggle && (
          <Switch checked={!!enabled} onChange={onToggle} label={`Enable ${title}`} disabled={toggleDisabled} />
        )}
      </div>
      {(open || keepMounted) && (
        <div id={bodyId} hidden={!open} className="px-4 pb-4 pt-3 space-y-3 border-t border-dark-border/40">
          {children}
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ Fields

interface TextFieldProps {
  label: ReactNode
  value: string
  onChange: (value: string) => void
  type?: 'text' | 'password' | 'email' | 'url' | 'number'
  placeholder?: string
  hint?: ReactNode
  /** Secrets default to "new-password" so password managers don't fill in the login password. */
  autoComplete?: string
}

export function TextField({ label, value, onChange, type = 'text', placeholder, hint, autoComplete }: TextFieldProps) {
  const id = useId()
  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-dark-text-secondary mb-1">{label}</label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete ?? (type === 'password' ? 'new-password' : 'off')}
        spellCheck={false}
        className="w-full bg-dark-bg-primary border border-dark-border rounded-md px-3 py-1.5 text-sm
                   text-dark-text-primary placeholder:text-dark-text-secondary/70
                   focus:outline-none focus:border-dark-accent-primary transition-colors"
      />
      {hint && <p className="text-[11px] text-dark-text-secondary mt-1">{hint}</p>}
    </div>
  )
}

/** Muted info box used for setup hints and links. */
export function InfoNote({ children }: { children: ReactNode }) {
  return <div className="text-xs text-dark-text-secondary bg-dark-bg-primary/60 rounded-md px-3 py-2">{children}</div>
}

// ------------------------------------------------------------------ Buttons

interface ActionButtonProps {
  onClick: () => void
  busy?: boolean
  disabled?: boolean
  variant?: 'primary' | 'secondary'
  title?: string
  children: ReactNode
}

export function ActionButton({ onClick, busy = false, disabled = false, variant = 'secondary', title, children }: ActionButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy || disabled}
      title={title}
      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors disabled:opacity-50
                  focus:outline-none focus-visible:ring-2 focus-visible:ring-dark-accent-primary ${
        variant === 'primary'
          ? 'bg-dark-accent-primary hover:bg-dark-accent-hover text-white'
          : 'bg-dark-bg-primary border border-dark-border text-dark-text-primary hover:border-dark-accent-primary'
      }`}
    >
      {busy && <Loader2 size={12} className="animate-spin" />}
      {children}
    </button>
  )
}

// ------------------------------------------------------------------ Action status

export interface ActionState {
  status: 'idle' | 'busy' | 'ok' | 'error'
  message?: string
}

/**
 * Run an async settings call and keep its outcome for <ActionStatus>.
 * Success messages clear after 2.5 s unless `sticky` (used for connection tests,
 * whose result stays until the next test or until `reset` is called).
 */
export function useAction({ sticky = false }: { sticky?: boolean } = {}) {
  const [state, setState] = useState<ActionState>({ status: 'idle' })
  const timer = useRef<ReturnType<typeof setTimeout>>()
  useEffect(() => () => clearTimeout(timer.current), [])

  const run = useCallback(async (fn: () => Promise<unknown>, okMessage = 'Saved', failPrefix = "Couldn't save") => {
    clearTimeout(timer.current)
    setState({ status: 'busy' })
    try {
      await fn()
      setState({ status: 'ok', message: okMessage })
      if (!sticky) timer.current = setTimeout(() => setState({ status: 'idle' }), 2500)
      return true
    } catch (err) {
      const detail = err instanceof Error && err.message ? err.message : 'request failed'
      // Servers often answer with the same words as the prefix ("Connection failed")
      const same = detail.replace(/\.$/, '').toLowerCase() === failPrefix.toLowerCase()
      setState({ status: 'error', message: same ? failPrefix : `${failPrefix}: ${detail}` })
      return false
    }
  }, [sticky])

  const reset = useCallback(() => {
    clearTimeout(timer.current)
    setState(prev => (prev.status === 'idle' || prev.status === 'busy' ? prev : { status: 'idle' }))
  }, [])

  return [state, run, reset] as const
}

/** Announces the result of a save/test (polite live region). */
export function ActionStatus({ state }: { state: ActionState }) {
  const ok = state.status === 'ok'
  const show = ok || state.status === 'error'
  return (
    <span
      role="status"
      className={`flex items-center gap-1 text-xs ${
        ok ? 'text-green-400 [.light_&]:text-green-700' : 'text-red-400 [.light_&]:text-red-700'
      }`}
    >
      {show && (ok ? <Check size={12} /> : <X size={12} />)}
      {show && state.message}
    </span>
  )
}
