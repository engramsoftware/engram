/**
 * Shared building blocks for the Settings screen (and other management pages).
 *
 * Every card follows one save rule: flipping a switch or picking an option
 * saves at once; typed values are drafts until Save (the card shows "Unsaved").
 * - Switch: a labelled role="switch" button
 * - StatusPill / UnsavedPill: the one status vocabulary (In use, On, Off, ...)
 * - SettingsCard: expandable card whose header is a real button; the enable
 *   switch sits beside the header instead of inside it
 * - TextField / PasswordField / TextArea / SelectField: inputs with labels
 * - Disclosure: a show/hide section that can keep its content mounted
 * - ConfirmButton: inline "are you sure" for risky actions
 * - useAction + ActionStatus: run a save/test call and show the outcome
 * - useDirty: report unsaved drafts so leaving Settings can ask first
 */

import {
  forwardRef, useCallback, useEffect, useId, useRef, useState, type ReactNode,
} from 'react'
import { Check, ChevronDown, ChevronRight, Eye, EyeOff, Loader2, X } from 'lucide-react'
import { useUIStore } from '../../stores/uiStore'

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

// ------------------------------------------------------------------ Badges and status

const BADGE_TONES = {
  green: 'text-green-400 bg-green-400/10 [.light_&]:text-green-800 [.light_&]:bg-green-600/10',
  blue: 'text-blue-400 bg-blue-400/10 [.light_&]:text-blue-700 [.light_&]:bg-blue-600/10',
  yellow: 'text-yellow-400 bg-yellow-400/10 [.light_&]:text-yellow-800 [.light_&]:bg-yellow-500/15',
  gray: 'text-dark-text-secondary bg-dark-bg-primary',
} as const

export function Badge({ tone = 'gray', children }: { tone?: keyof typeof BADGE_TONES; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-full whitespace-nowrap ${BADGE_TONES[tone]}`}>
      {children}
    </span>
  )
}

/** The status vocabulary used in every card header. */
export type CardStatus = 'in-use' | 'on' | 'off' | 'needs-setup' | 'default'

const STATUS_META: Record<CardStatus, { tone: keyof typeof BADGE_TONES; label: string }> = {
  'in-use': { tone: 'green', label: 'In use' },
  on: { tone: 'green', label: 'On' },
  off: { tone: 'gray', label: 'Off' },
  'needs-setup': { tone: 'yellow', label: 'Needs setup' },
  default: { tone: 'green', label: 'Default' },
}

export function StatusPill({ status }: { status: CardStatus }) {
  const meta = STATUS_META[status]
  return <Badge tone={meta.tone}>{meta.label}</Badge>
}

export function UnsavedPill() {
  return <Badge tone="blue">Unsaved</Badge>
}

// ------------------------------------------------------------------ SettingsCard

interface SettingsCardProps {
  title: string
  subtitle?: string
  icon?: ReactNode
  /** One status pill from the shared vocabulary. */
  status?: CardStatus
  /** Shows the "Unsaved" pill while typed changes wait for Save. */
  unsaved?: boolean
  /** Extra badges shown next to the title (e.g. an add-in's type). */
  badges?: ReactNode
  /** A second line under the subtitle, e.g. "Key saved · sk-…abcd". */
  meta?: ReactNode
  /** Extra content between the header and the switch. */
  aside?: ReactNode
  /** When set, renders an enable switch and highlights the card while enabled. */
  enabled?: boolean
  onToggle?: (next: boolean) => void
  toggleDisabled?: boolean
  /** Label for the switch; defaults to "Turn on <title>". */
  toggleLabel?: string
  defaultOpen?: boolean
  /** Controlled open state (optional). */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** Keep the body mounted (hidden) while collapsed, so its state survives. */
  keepMounted?: boolean
  children: ReactNode
}

export function SettingsCard({
  title, subtitle, icon, status, unsaved, badges, meta, aside, enabled, onToggle, toggleDisabled, toggleLabel,
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
              {status && <StatusPill status={status} />}
              {unsaved && <UnsavedPill />}
              {badges}
            </span>
            {subtitle && <span className="block text-xs text-dark-text-secondary truncate">{subtitle}</span>}
            {meta && <span className="block text-[11px] text-dark-text-secondary mt-0.5 truncate">{meta}</span>}
          </span>
        </button>
        {aside}
        {onToggle && (
          <Switch checked={!!enabled} onChange={onToggle} label={toggleLabel ?? `Turn on ${title}`} disabled={toggleDisabled} />
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

const INPUT_CLASS = `w-full bg-dark-bg-primary border border-dark-border rounded-md px-3 py-2 sm:py-1.5 text-sm
  text-dark-text-primary placeholder:text-dark-text-secondary/70 disabled:opacity-60
  focus:outline-none focus:border-dark-accent-primary transition-colors`

interface TextFieldProps {
  label: ReactNode
  value: string
  onChange: (value: string) => void
  type?: 'text' | 'password' | 'email' | 'url' | 'number'
  placeholder?: string
  hint?: ReactNode
  /** Secrets default to "new-password" so password managers don't fill in the login password. */
  autoComplete?: string
  disabled?: boolean
  min?: number
  max?: number
}

export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, value, onChange, type = 'text', placeholder, hint, autoComplete, disabled, min, max }, ref,
) {
  const id = useId()
  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-dark-text-secondary mb-1">{label}</label>
      <input
        ref={ref}
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete ?? (type === 'password' ? 'new-password' : 'off')}
        spellCheck={false}
        disabled={disabled}
        min={min}
        max={max}
        aria-describedby={hint ? `${id}-hint` : undefined}
        className={INPUT_CLASS}
      />
      {hint && <p id={`${id}-hint`} className="text-[11px] text-dark-text-secondary mt-1">{hint}</p>}
    </div>
  )
})

/** Password input with a show/hide toggle. */
export const PasswordField = forwardRef<HTMLInputElement, Omit<TextFieldProps, 'type'>>(function PasswordField(
  { label, value, onChange, placeholder, hint, autoComplete, disabled }, ref,
) {
  const id = useId()
  const [shown, setShown] = useState(false)
  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-dark-text-secondary mb-1">{label}</label>
      <div className="relative">
        <input
          ref={ref}
          id={id}
          type={shown ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          autoComplete={autoComplete ?? 'new-password'}
          spellCheck={false}
          disabled={disabled}
          aria-describedby={hint ? `${id}-hint` : undefined}
          className={`${INPUT_CLASS} pr-10`}
        />
        <button
          type="button"
          onClick={() => setShown(s => !s)}
          aria-label={shown ? 'Hide password' : 'Show password'}
          aria-pressed={shown}
          className="absolute right-1 top-1/2 -translate-y-1/2 p-1.5 rounded text-dark-text-secondary
                     hover:text-dark-text-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-dark-accent-primary"
        >
          {shown ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      </div>
      {hint && <p id={`${id}-hint`} className="text-[11px] text-dark-text-secondary mt-1">{hint}</p>}
    </div>
  )
})

export function TextArea({ label, value, onChange, placeholder, hint, rows = 4 }: {
  label: ReactNode; value: string; onChange: (value: string) => void; placeholder?: string; hint?: ReactNode; rows?: number
}) {
  const id = useId()
  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-dark-text-secondary mb-1">{label}</label>
      <textarea
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        rows={rows}
        aria-describedby={hint ? `${id}-hint` : undefined}
        className={`${INPUT_CLASS} resize-y`}
      />
      {hint && <p id={`${id}-hint`} className="text-[11px] text-dark-text-secondary mt-1">{hint}</p>}
    </div>
  )
}

export interface SelectOption { value: string; label: string }

export function SelectField({ label, value, onChange, options, hint, disabled, hideLabel = false }: {
  label: string; value: string; onChange: (value: string) => void; options: SelectOption[]
  hint?: ReactNode; disabled?: boolean; hideLabel?: boolean
}) {
  const id = useId()
  return (
    <div>
      <label htmlFor={id} className={hideLabel ? 'sr-only' : 'block text-xs font-medium text-dark-text-secondary mb-1'}>{label}</label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        aria-describedby={hint ? `${id}-hint` : undefined}
        className={`${INPUT_CLASS} cursor-pointer`}
      >
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      {hint && <p id={`${id}-hint`} className="text-[11px] text-dark-text-secondary mt-1">{hint}</p>}
    </div>
  )
}

/** Muted info box used for setup hints and links. */
export function InfoNote({ children }: { children: ReactNode }) {
  return <div className="text-xs text-dark-text-secondary bg-dark-bg-primary/60 rounded-md px-3 py-2">{children}</div>
}

/** Show/hide section. With keepMounted, hidden content keeps its state. */
export function Disclosure({ summary, children, defaultOpen = false, open: openProp, onOpenChange, keepMounted = false }: {
  summary: ReactNode; children: ReactNode; defaultOpen?: boolean
  open?: boolean; onOpenChange?: (open: boolean) => void; keepMounted?: boolean
}) {
  const [openState, setOpenState] = useState(defaultOpen)
  const open = openProp ?? openState
  const bodyId = useId()
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={bodyId}
        onClick={() => { if (openProp === undefined) setOpenState(!open); onOpenChange?.(!open) }}
        className="flex items-center gap-1 text-xs text-dark-text-secondary hover:text-dark-text-primary rounded
                   py-1 min-h-[40px] sm:min-h-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-dark-accent-primary"
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        {summary}
      </button>
      {(open || keepMounted) && (
        <div id={bodyId} hidden={!open} className="mt-2 space-y-3">{children}</div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ Buttons

interface ActionButtonProps {
  onClick: () => void
  busy?: boolean
  disabled?: boolean
  variant?: 'primary' | 'secondary' | 'danger'
  title?: string
  children: ReactNode
}

const BUTTON_VARIANTS = {
  primary: 'bg-dark-accent-primary hover:bg-dark-accent-hover text-white',
  secondary: 'bg-dark-bg-primary border border-dark-border text-dark-text-primary hover:border-dark-accent-primary',
  danger: 'bg-red-600 hover:bg-red-500 text-white',
} as const

export const ActionButton = forwardRef<HTMLButtonElement, ActionButtonProps>(function ActionButton(
  { onClick, busy = false, disabled = false, variant = 'secondary', title, children }, ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      onClick={onClick}
      disabled={busy || disabled}
      title={title}
      className={`inline-flex items-center justify-center gap-1.5 px-3 py-1.5 min-h-[40px] sm:min-h-0 rounded-md
                  text-xs font-medium transition-colors disabled:opacity-50
                  focus:outline-none focus-visible:ring-2 focus-visible:ring-dark-accent-primary ${BUTTON_VARIANTS[variant]}`}
    >
      {busy && <Loader2 size={12} className="animate-spin" />}
      {children}
    </button>
  )
})

/** A row of card actions: secondary actions first, Save (primary) last. */
export function ActionRow({ children }: { children: ReactNode }) {
  return <div className="flex items-center gap-2 flex-wrap pt-1">{children}</div>
}

interface ConfirmButtonProps {
  /** Text on the button before confirming. */
  label: ReactNode
  /** The question shown once the button is pressed. */
  prompt: ReactNode
  /** Text on the button that carries out the action. */
  confirmLabel: string
  onConfirm: () => void | Promise<unknown>
  /** Set false to act immediately without asking (e.g. nothing risky changed). */
  needsConfirm?: boolean
  busy?: boolean
  disabled?: boolean
  danger?: boolean
  variant?: 'primary' | 'secondary'
}

/** Inline "are you sure" step for risky actions. Cancel (or Escape) sends nothing. */
export function ConfirmButton({
  label, prompt, confirmLabel, onConfirm, needsConfirm = true, busy, disabled, danger = false, variant = 'secondary',
}: ConfirmButtonProps) {
  const [armed, setArmed] = useState(false)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  // After Cancel or Confirm, focus returns to the button (when it is still there)
  const returnFocus = useRef(false)
  const promptId = useId()
  useEffect(() => {
    if (armed) cancelRef.current?.focus()
    else if (returnFocus.current) { returnFocus.current = false; triggerRef.current?.focus() }
  }, [armed])
  const disarm = () => { returnFocus.current = true; setArmed(false) }

  if (!armed) {
    return (
      <ActionButton
        ref={triggerRef}
        variant={variant}
        busy={busy}
        disabled={disabled}
        onClick={() => { if (needsConfirm) setArmed(true); else void onConfirm() }}
      >
        {label}
      </ActionButton>
    )
  }
  return (
    <div
      role="group"
      aria-labelledby={promptId}
      onKeyDown={(e) => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); disarm() } }}
      className={`flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 ${
        danger ? 'border-red-500/40 bg-red-500/5' : 'border-dark-border bg-dark-bg-primary/60'
      }`}
    >
      <span id={promptId} className="text-xs text-dark-text-primary">{prompt}</span>
      <ActionButton ref={cancelRef} onClick={disarm}>Cancel</ActionButton>
      <ActionButton variant={danger ? 'danger' : 'primary'} onClick={() => { disarm(); void onConfirm() }}>
        {confirmLabel}
      </ActionButton>
    </div>
  )
}

// ------------------------------------------------------------------ Action status

export interface ActionState {
  status: 'idle' | 'busy' | 'ok' | 'error'
  message?: string
}

/** Turn an error into readable text (API errors may carry a server message). */
export function errorText(err: unknown, fallback = 'request failed'): string {
  return err instanceof Error && err.message ? err.message : fallback
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
      const detail = errorText(err)
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

/** Only shows failures (for actions whose success is visible anyway, like a switch). */
export function ErrorStatus({ state }: { state: ActionState }) {
  return <ActionStatus state={state.status === 'error' ? state : { status: 'idle' }} />
}

// ------------------------------------------------------------------ Layout and keyboard helpers

const PHONE_QUERY = '(max-width: 767px)'

/** True below the md breakpoint; updates when the window is resized. */
export function useIsPhone() {
  const [phone, setPhone] = useState(() => window.matchMedia(PHONE_QUERY).matches)
  useEffect(() => {
    const mq = window.matchMedia(PHONE_QUERY)
    const onChange = () => setPhone(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  return phone
}

/**
 * For radio groups where choosing saves at once: arrow keys only move focus
 * (instead of selecting, as native radios do); Space or a click selects.
 */
export function moveRadioFocus(e: React.KeyboardEvent<HTMLInputElement>) {
  const forward = e.key === 'ArrowDown' || e.key === 'ArrowRight'
  if (!forward && e.key !== 'ArrowUp' && e.key !== 'ArrowLeft') return
  e.preventDefault()
  const radios = [...document.querySelectorAll<HTMLInputElement>(`input[type="radio"][name="${e.currentTarget.name}"]`)]
    .filter(r => !r.disabled && r.getClientRects().length > 0) // skip hidden rows
  const i = radios.indexOf(e.currentTarget)
  radios[(i + (forward ? 1 : -1) + radios.length) % radios.length]?.focus()
}

// ------------------------------------------------------------------ Unsaved drafts

/** Report a card's unsaved drafts so leaving Settings can ask before discarding them. */
export function useDirty(dirty: boolean) {
  const id = useId()
  const setCardDirty = useUIStore(s => s.setCardDirty)
  useEffect(() => { setCardDirty(id, dirty) }, [id, dirty, setCardDirty])
  useEffect(() => () => setCardDirty(id, false), [id, setCardDirty])
}
