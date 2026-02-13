/**
 * Routes addin IDs to their frontend panel components.
 * GUI addins register their panels here.
 * When a new GUI addin is created, add its component to the PANELS map.
 */

import { lazy, Suspense } from 'react'
import { Loader2, Puzzle } from 'lucide-react'

const PomodoroPanel = lazy(() => import('./PomodoroPanel'))
const MoodPanel = lazy(() => import('./MoodPanel'))
const SkillVoyagerPanel = lazy(() => import('./SkillVoyagerPanel'))

/** Map of addin ID -> lazy-loaded panel component. */
const PANELS: Record<string, React.LazyExoticComponent<() => JSX.Element>> = {
  pomodoro: PomodoroPanel,
  mood_journal: MoodPanel,
  skill_voyager: SkillVoyagerPanel,
}

interface Props {
  addinId: string
  addinName: string
}

/**
 * Renders the panel for a GUI addin by its ID.
 * Shows a fallback message if no panel is registered.
 */
export default function AddinPanelRouter({ addinId, addinName }: Props) {
  const Panel = PANELS[addinId]

  if (!Panel) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3 p-6">
        <Puzzle size={40} className="text-dark-text-secondary/40" />
        <p className="text-dark-text-secondary text-sm text-center">
          <strong>{addinName}</strong> is enabled but has no panel UI yet.
        </p>
        <p className="text-dark-text-secondary/60 text-xs">
          A developer needs to register a panel component for this add-in.
        </p>
      </div>
    )
  }

  return (
    <Suspense
      fallback={
        <div className="h-full flex items-center justify-center">
          <Loader2 size={24} className="animate-spin text-dark-text-secondary" />
        </div>
      }
    >
      <Panel />
    </Suspense>
  )
}
