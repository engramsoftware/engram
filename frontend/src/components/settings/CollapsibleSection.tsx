/**
 * Reusable collapsible settings section.
 * Wraps any settings content in a chevron-toggled card with optional
 * enable toggle and status badge.
 *
 * @param title - Section heading
 * @param subtitle - Optional description under heading
 * @param icon - Lucide icon element
 * @param children - Section content (rendered when expanded)
 * @param defaultOpen - Whether section starts expanded
 * @param enabled - If defined, shows an enable/disable toggle
 * @param onToggle - Callback when enable toggle is clicked
 * @param badge - Optional badge text (e.g. "configured", "3 models")
 * @param badgeColor - Badge color variant
 */

import { useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight, Zap } from 'lucide-react'

interface Props {
  title: string
  subtitle?: string
  icon: ReactNode
  children: ReactNode
  defaultOpen?: boolean
  enabled?: boolean
  onToggle?: (next: boolean) => void
  badge?: string
  badgeColor?: 'green' | 'blue' | 'yellow' | 'gray'
}

const BADGE_STYLES: Record<string, string> = {
  green: 'text-green-400 bg-green-400/10',
  blue: 'text-blue-400 bg-blue-400/10',
  yellow: 'text-yellow-400 bg-yellow-400/10',
  gray: 'text-dark-text-secondary bg-dark-bg-primary',
}

export default function CollapsibleSection({
  title,
  subtitle,
  icon,
  children,
  defaultOpen = false,
  enabled,
  onToggle,
  badge,
  badgeColor = 'green',
}: Props) {
  const [isOpen, setIsOpen] = useState(defaultOpen)

  const handleToggle = (e: React.MouseEvent) => {
    e.stopPropagation()
    onToggle?.(!enabled)
  }

  return (
    <div className={`rounded-lg border transition-colors ${
      enabled === true
        ? 'bg-dark-bg-secondary border-dark-accent-primary/30'
        : 'bg-dark-bg-secondary/50 border-dark-border/50'
    }`}>
      {/* Header — always visible, clickable to expand */}
      <div
        className="flex items-center gap-3 px-4 py-3 cursor-pointer select-none hover:bg-dark-bg-secondary/80 transition-colors"
        onClick={() => setIsOpen(!isOpen)}
      >
        {/* Chevron */}
        {isOpen
          ? <ChevronDown size={14} className="text-dark-text-secondary flex-shrink-0" />
          : <ChevronRight size={14} className="text-dark-text-secondary flex-shrink-0" />
        }

        {/* Icon */}
        <span className="text-dark-text-secondary flex-shrink-0">{icon}</span>

        {/* Title + subtitle */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className={`text-sm font-medium ${
              enabled !== false ? 'text-dark-text-primary' : 'text-dark-text-secondary'
            }`}>
              {title}
            </span>
            {enabled && (
              <span className="flex items-center gap-1 text-[10px] font-medium text-green-400 bg-green-400/10 px-1.5 py-0.5 rounded-full">
                <Zap size={8} /> Active
              </span>
            )}
            {badge && (
              <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${BADGE_STYLES[badgeColor]}`}>
                {badge}
              </span>
            )}
          </div>
          {subtitle && (
            <p className="text-xs text-dark-text-secondary truncate">{subtitle}</p>
          )}
        </div>

        {/* Enable toggle (optional) */}
        {onToggle !== undefined && (
          <button
            onClick={handleToggle}
            className={`relative inline-flex items-center w-10 h-6 rounded-full transition-colors flex-shrink-0 ${
              enabled ? 'bg-dark-accent-primary' : 'bg-dark-border'
            }`}
          >
            <span className={`inline-block w-4 h-4 rounded-full bg-white shadow-sm transition-transform ${
              enabled ? 'translate-x-5' : 'translate-x-1'
            }`} />
          </button>
        )}
      </div>

      {/* Collapsible content */}
      {isOpen && (
        <div className="px-4 pb-4 pt-1 border-t border-dark-border/30">
          {children}
        </div>
      )}
    </div>
  )
}
