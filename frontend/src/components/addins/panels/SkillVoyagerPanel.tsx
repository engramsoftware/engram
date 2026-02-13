/**
 * Skill Voyager dashboard panel.
 * Shows the skill library, learning progress, recent evaluations,
 * and composition tree. Mounted as a GUI addin sidebar panel.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Sparkles, Brain, TrendingUp, TrendingDown, Target,
  BookOpen, GitBranch, Play, Trash2,
  ChevronDown, ChevronRight, Loader2, RefreshCw,
  CheckCircle2, XCircle, AlertTriangle, Clock,
} from 'lucide-react'
import { addinsApi } from '../../../services/api'

/** Skill data from the backend. */
interface Skill {
  id: string
  name: string
  skill_type: string
  description: string
  strategy: string
  trigger_patterns: string[]
  confidence: number
  times_used: number
  times_succeeded: number
  times_failed: number
  parent_skill_ids: string[]
  child_skill_ids: string[]
  state: string
  source: string
  created_at: number
  last_used_at: number
}

interface Evaluation {
  id: string
  skill_id: string
  skill_name: string
  skill_type: string
  score: number
  reasoning: string
  query_text: string
  evaluated_at: number
}

interface DashboardData {
  stats: {
    total_skills: number
    by_state: Record<string, number>
    by_type: Record<string, number>
    avg_confidence: number
    total_evaluations: number
    avg_evaluation_score: number
  }
  skills: Skill[]
  recent_evaluations: Evaluation[]
  auto_learn: boolean
  curriculum_enabled: boolean
  messages_processed: number
}

/** Call the skill_voyager addin's handle_action endpoint (via centralized API with auth). */
async function voyagerAction(action: string, payload: Record<string, unknown> = {}) {
  return addinsApi.action('skill_voyager', action, payload)
}

const STATE_ICONS: Record<string, React.ReactNode> = {
  candidate: <Clock size={12} className="text-yellow-400" />,
  verified: <CheckCircle2 size={12} className="text-blue-400" />,
  mastered: <Sparkles size={12} className="text-green-400" />,
  deprecated: <XCircle size={12} className="text-red-400/60" />,
}

const STATE_COLORS: Record<string, string> = {
  candidate: 'text-yellow-400 bg-yellow-400/10',
  verified: 'text-blue-400 bg-blue-400/10',
  mastered: 'text-green-400 bg-green-400/10',
  deprecated: 'text-red-400/60 bg-red-400/5',
}

const TYPE_LABELS: Record<string, string> = {
  search_strategy: 'Search',
  response_format: 'Format',
  retrieval_combo: 'Multi-Source',
  conversation_pattern: 'Conv.',
  error_recovery: 'Recovery',
}

export default function SkillVoyagerPanel() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeSection, setActiveSection] = useState<'overview' | 'skills' | 'evals' | 'curriculum'>('overview')
  const [expandedSkill, setExpandedSkill] = useState<string | null>(null)
  const [curriculumResults, setCurriculumResults] = useState<any[] | null>(null)
  const [runningCurriculum, setRunningCurriculum] = useState(false)

  const fetchDashboard = useCallback(async () => {
    try {
      setLoading(true)
      const result = await voyagerAction('get_dashboard')
      setData(result)
      setError(null)
    } catch (e: any) {
      setError(e.message || 'Failed to load dashboard')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchDashboard() }, [fetchDashboard])

  const handleRunCurriculum = async () => {
    setRunningCurriculum(true)
    try {
      const result = await voyagerAction('run_curriculum')
      setCurriculumResults(result.proposals || [])
    } catch (e: any) {
      setError(e.message)
    } finally {
      setRunningCurriculum(false)
    }
  }

  const handleDeleteSkill = async (skillId: string) => {
    try {
      await voyagerAction('delete_skill', { skill_id: skillId })
      fetchDashboard()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const handleToggleAutoLearn = async () => {
    try {
      const result = await voyagerAction('toggle_auto_learn')
      setData(prev => prev ? { ...prev, auto_learn: result.auto_learn } : prev)
    } catch (e: any) {
      setError(e.message)
    }
  }

  if (loading && !data) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <Loader2 size={24} className="animate-spin text-dark-accent-primary" />
          <p className="text-sm text-dark-text-secondary">Loading Skill Voyager...</p>
        </div>
      </div>
    )
  }

  if (error && !data) {
    return (
      <div className="h-full flex items-center justify-center p-6">
        <div className="text-center">
          <AlertTriangle size={32} className="text-yellow-400 mx-auto mb-3" />
          <p className="text-sm text-dark-text-secondary">{error}</p>
          <button
            onClick={fetchDashboard}
            className="mt-3 text-xs text-dark-accent-primary hover:underline"
          >
            Try again
          </button>
        </div>
      </div>
    )
  }

  if (!data) return <></>

  const { stats, skills, recent_evaluations } = data

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-2xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-purple-500/10">
              <Brain size={20} className="text-purple-400" />
            </div>
            <div>
              <h1 className="text-xl font-semibold text-dark-text-primary">Skill Voyager</h1>
              <p className="text-xs text-dark-text-secondary">
                {stats.total_skills} skills · {data.messages_processed} messages processed
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleToggleAutoLearn}
              className={`text-[10px] px-2 py-1 rounded-full font-medium transition-colors ${
                data.auto_learn
                  ? 'text-green-400 bg-green-400/10 hover:bg-green-400/20'
                  : 'text-dark-text-secondary bg-dark-bg-primary hover:bg-dark-bg-secondary'
              }`}
            >
              {data.auto_learn ? 'Learning ON' : 'Learning OFF'}
            </button>
            <button
              onClick={fetchDashboard}
              className="p-1.5 rounded-lg text-dark-text-secondary hover:text-dark-text-primary hover:bg-dark-bg-secondary transition-colors"
            >
              <RefreshCw size={14} />
            </button>
          </div>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-4 gap-3 mb-6">
          <StatCard
            label="Mastered"
            value={stats.by_state?.mastered || 0}
            icon={<Sparkles size={14} className="text-green-400" />}
            color="green"
          />
          <StatCard
            label="Verified"
            value={stats.by_state?.verified || 0}
            icon={<CheckCircle2 size={14} className="text-blue-400" />}
            color="blue"
          />
          <StatCard
            label="Candidates"
            value={stats.by_state?.candidate || 0}
            icon={<Clock size={14} className="text-yellow-400" />}
            color="yellow"
          />
          <StatCard
            label="Avg Score"
            value={stats.avg_evaluation_score.toFixed(1)}
            icon={<Target size={14} className="text-purple-400" />}
            color="purple"
          />
        </div>

        {/* Confidence Bar */}
        <div className="mb-6 bg-dark-bg-secondary rounded-lg p-3">
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-[11px] text-dark-text-secondary font-medium">Average Confidence</span>
            <span className="text-[11px] text-dark-text-primary font-mono">
              {(stats.avg_confidence * 100).toFixed(0)}%
            </span>
          </div>
          <div className="h-2 bg-dark-bg-primary rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-purple-500 to-blue-400 rounded-full transition-all duration-500"
              style={{ width: `${Math.min(stats.avg_confidence * 100, 100)}%` }}
            />
          </div>
        </div>

        {/* Section Tabs */}
        <div className="flex gap-1 mb-4 bg-dark-bg-secondary rounded-lg p-1">
          {(['overview', 'skills', 'evals', 'curriculum'] as const).map(section => (
            <button
              key={section}
              onClick={() => setActiveSection(section)}
              className={`flex-1 text-[11px] py-1.5 rounded-md font-medium transition-colors ${
                activeSection === section
                  ? 'bg-dark-accent-primary text-white'
                  : 'text-dark-text-secondary hover:text-dark-text-primary'
              }`}
            >
              {section === 'overview' ? 'Overview' :
               section === 'skills' ? `Skills (${stats.total_skills})` :
               section === 'evals' ? `Evals (${stats.total_evaluations})` :
               'Curriculum'}
            </button>
          ))}
        </div>

        {/* Section Content */}
        {activeSection === 'overview' && (
          <OverviewSection stats={stats} skills={skills} />
        )}

        {activeSection === 'skills' && (
          <SkillsSection
            skills={skills}
            expandedSkill={expandedSkill}
            onToggleExpand={id => setExpandedSkill(expandedSkill === id ? null : id)}
            onDelete={handleDeleteSkill}
          />
        )}

        {activeSection === 'evals' && (
          <EvalsSection evaluations={recent_evaluations} />
        )}

        {activeSection === 'curriculum' && (
          <CurriculumSection
            results={curriculumResults}
            running={runningCurriculum}
            onRun={handleRunCurriculum}
          />
        )}
      </div>
    </div>
  )
}


/** Small stat card for the top row. */
function StatCard({ label, value, icon, color }: {
  label: string; value: number | string; icon: React.ReactNode; color: string
}) {
  const borderColors: Record<string, string> = {
    green: 'border-green-400/20',
    blue: 'border-blue-400/20',
    yellow: 'border-yellow-400/20',
    purple: 'border-purple-400/20',
  }
  return (
    <div className={`bg-dark-bg-secondary rounded-lg p-3 border ${borderColors[color] || 'border-dark-border/30'}`}>
      <div className="flex items-center gap-1.5 mb-1">{icon}<span className="text-[10px] text-dark-text-secondary">{label}</span></div>
      <span className="text-lg font-semibold text-dark-text-primary">{value}</span>
    </div>
  )
}


/** Overview: skill type distribution + recent activity. */
function OverviewSection({ stats, skills }: { stats: DashboardData['stats']; skills: Skill[] }) {
  const topSkills = skills
    .filter(s => s.state !== 'deprecated')
    .sort((a, b) => b.confidence - a.confidence)
    .slice(0, 5)

  return (
    <div className="space-y-4">
      {/* Type Distribution */}
      <div className="bg-dark-bg-secondary rounded-lg p-4">
        <h3 className="text-xs font-semibold text-dark-text-secondary uppercase tracking-wider mb-3">
          Skill Types
        </h3>
        <div className="space-y-2">
          {Object.entries(stats.by_type).map(([type, count]) => (
            <div key={type} className="flex items-center gap-2">
              <span className="text-[11px] text-dark-text-secondary w-24 truncate">
                {TYPE_LABELS[type] || type}
              </span>
              <div className="flex-1 h-1.5 bg-dark-bg-primary rounded-full overflow-hidden">
                <div
                  className="h-full bg-purple-500/60 rounded-full"
                  style={{ width: `${Math.min((count / Math.max(stats.total_skills, 1)) * 100, 100)}%` }}
                />
              </div>
              <span className="text-[10px] text-dark-text-secondary font-mono w-6 text-right">{count}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Top Skills */}
      <div className="bg-dark-bg-secondary rounded-lg p-4">
        <h3 className="text-xs font-semibold text-dark-text-secondary uppercase tracking-wider mb-3">
          Top Skills by Confidence
        </h3>
        {topSkills.length === 0 ? (
          <p className="text-xs text-dark-text-secondary/50 italic">No skills yet</p>
        ) : (
          <div className="space-y-2">
            {topSkills.map(skill => (
              <div key={skill.id} className="flex items-center gap-2">
                {STATE_ICONS[skill.state]}
                <span className="text-[11px] text-dark-text-primary flex-1 truncate">{skill.name}</span>
                <div className="w-16 h-1.5 bg-dark-bg-primary rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      skill.confidence >= 0.8 ? 'bg-green-400' :
                      skill.confidence >= 0.6 ? 'bg-blue-400' :
                      skill.confidence >= 0.4 ? 'bg-yellow-400' : 'bg-red-400'
                    }`}
                    style={{ width: `${skill.confidence * 100}%` }}
                  />
                </div>
                <span className="text-[10px] text-dark-text-secondary font-mono w-10 text-right">
                  {(skill.confidence * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}


/** Full skill library with expandable cards. */
function SkillsSection({ skills, expandedSkill, onToggleExpand, onDelete }: {
  skills: Skill[]
  expandedSkill: string | null
  onToggleExpand: (id: string) => void
  onDelete: (id: string) => void
}) {
  const [filter, setFilter] = useState<string>('all')

  const filtered = filter === 'all'
    ? skills
    : skills.filter(s => s.state === filter)

  return (
    <div>
      {/* Filter bar */}
      <div className="flex gap-1 mb-3">
        {['all', 'mastered', 'verified', 'candidate', 'deprecated'].map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`text-[10px] px-2 py-1 rounded-md font-medium transition-colors ${
              filter === f
                ? 'bg-dark-accent-primary/20 text-dark-accent-primary'
                : 'text-dark-text-secondary hover:text-dark-text-primary'
            }`}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <p className="text-xs text-dark-text-secondary/50 italic py-4 text-center">
          No skills match this filter
        </p>
      ) : (
        <div className="space-y-2">
          {filtered.map(skill => (
            <div
              key={skill.id}
              className="bg-dark-bg-secondary rounded-lg border border-dark-border/30 overflow-hidden"
            >
              {/* Skill header */}
              <div
                className="flex items-center gap-2 px-3 py-2.5 cursor-pointer hover:bg-dark-bg-secondary/80 transition-colors"
                onClick={() => onToggleExpand(skill.id)}
              >
                {expandedSkill === skill.id
                  ? <ChevronDown size={12} className="text-dark-text-secondary" />
                  : <ChevronRight size={12} className="text-dark-text-secondary" />
                }
                {STATE_ICONS[skill.state]}
                <span className="text-[11px] text-dark-text-primary font-medium flex-1 truncate">
                  {skill.name}
                </span>
                <span className={`text-[9px] px-1.5 py-0.5 rounded ${STATE_COLORS[skill.state] || ''}`}>
                  {skill.state}
                </span>
                <span className="text-[10px] text-dark-text-secondary font-mono">
                  {(skill.confidence * 100).toFixed(0)}%
                </span>
              </div>

              {/* Expanded details */}
              {expandedSkill === skill.id && (
                <div className="px-3 pb-3 pt-1 border-t border-dark-border/20 space-y-2">
                  <div>
                    <span className="text-[10px] text-dark-text-secondary/60 uppercase">Strategy</span>
                    <p className="text-[11px] text-dark-text-primary mt-0.5">{skill.strategy}</p>
                  </div>
                  <div className="flex gap-4 text-[10px] text-dark-text-secondary">
                    <span>Used: {skill.times_used}</span>
                    <span className="text-green-400">Success: {skill.times_succeeded}</span>
                    <span className="text-red-400">Failed: {skill.times_failed}</span>
                    <span>Type: {TYPE_LABELS[skill.skill_type] || skill.skill_type}</span>
                    <span>Source: {skill.source}</span>
                  </div>
                  {skill.trigger_patterns.length > 0 && (
                    <div>
                      <span className="text-[10px] text-dark-text-secondary/60 uppercase">Triggers</span>
                      <div className="flex flex-wrap gap-1 mt-0.5">
                        {skill.trigger_patterns.map((t, i) => (
                          <span key={i} className="text-[10px] bg-dark-bg-primary text-dark-text-secondary px-1.5 py-0.5 rounded">
                            {t}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  {(skill.parent_skill_ids.length > 0 || skill.child_skill_ids.length > 0) && (
                    <div className="flex gap-4 text-[10px]">
                      {skill.parent_skill_ids.length > 0 && (
                        <span className="text-purple-400">
                          <GitBranch size={10} className="inline mr-1" />
                          {skill.parent_skill_ids.length} parent(s)
                        </span>
                      )}
                      {skill.child_skill_ids.length > 0 && (
                        <span className="text-blue-400">
                          {skill.child_skill_ids.length} child(ren)
                        </span>
                      )}
                    </div>
                  )}
                  <div className="flex justify-end">
                    <button
                      onClick={(e) => { e.stopPropagation(); onDelete(skill.id) }}
                      className="text-[10px] text-red-400/60 hover:text-red-400 flex items-center gap-1 transition-colors"
                    >
                      <Trash2 size={10} /> Delete
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}


/** Recent evaluations list. */
function EvalsSection({ evaluations }: { evaluations: Evaluation[] }) {
  if (evaluations.length === 0) {
    return (
      <div className="text-center py-8">
        <Target size={32} className="text-dark-text-secondary/30 mx-auto mb-2" />
        <p className="text-xs text-dark-text-secondary/50">No evaluations yet</p>
        <p className="text-[10px] text-dark-text-secondary/30 mt-1">
          Evaluations appear after skills are applied to messages
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      {evaluations.map(ev => (
        <div key={ev.id} className="bg-dark-bg-secondary rounded-lg p-3 border border-dark-border/20">
          <div className="flex items-center gap-2 mb-1">
            {ev.score >= 4 ? <TrendingUp size={12} className="text-green-400" /> :
             ev.score >= 3 ? <Target size={12} className="text-yellow-400" /> :
             <TrendingDown size={12} className="text-red-400" />}
            <span className="text-[11px] text-dark-text-primary font-medium">
              {ev.skill_name || 'Unknown'}
            </span>
            <span className={`text-[10px] font-mono font-bold ${
              ev.score >= 4 ? 'text-green-400' :
              ev.score >= 3 ? 'text-yellow-400' : 'text-red-400'
            }`}>
              {ev.score.toFixed(1)}/5
            </span>
            <span className="text-[10px] text-dark-text-secondary/40 ml-auto">
              {new Date(ev.evaluated_at * 1000).toLocaleTimeString()}
            </span>
          </div>
          <p className="text-[10px] text-dark-text-secondary truncate">{ev.reasoning}</p>
          {ev.query_text && (
            <p className="text-[10px] text-dark-text-secondary/40 truncate mt-0.5">
              Query: {ev.query_text}
            </p>
          )}
        </div>
      ))}
    </div>
  )
}


/** Curriculum engine controls and results. */
function CurriculumSection({ results, running, onRun }: {
  results: any[] | null; running: boolean; onRun: () => void
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-xs font-semibold text-dark-text-primary">Curriculum Engine</h3>
          <p className="text-[10px] text-dark-text-secondary">
            Analyzes gaps in your skill library and proposes new skills to learn
          </p>
        </div>
        <button
          onClick={onRun}
          disabled={running}
          className="flex items-center gap-1.5 text-[11px] bg-purple-500/20 text-purple-400
                     hover:bg-purple-500/30 px-3 py-1.5 rounded-lg transition-colors
                     disabled:opacity-50"
        >
          {running ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
          {running ? 'Analyzing...' : 'Run Curriculum'}
        </button>
      </div>

      {results === null ? (
        <div className="text-center py-8">
          <BookOpen size={32} className="text-dark-text-secondary/30 mx-auto mb-2" />
          <p className="text-xs text-dark-text-secondary/50">
            Click "Run Curriculum" to analyze skill gaps
          </p>
        </div>
      ) : results.length === 0 ? (
        <div className="text-center py-8">
          <CheckCircle2 size={32} className="text-green-400/40 mx-auto mb-2" />
          <p className="text-xs text-dark-text-secondary">No gaps found — skill library is comprehensive</p>
        </div>
      ) : (
        <div className="space-y-2">
          {results.map((p, i) => (
            <div key={i} className="bg-dark-bg-secondary rounded-lg p-3 border border-dark-border/20">
              <div className="flex items-center gap-2 mb-1">
                <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${
                  p.level <= 1 ? 'text-green-400 bg-green-400/10' :
                  p.level === 2 ? 'text-blue-400 bg-blue-400/10' :
                  'text-purple-400 bg-purple-400/10'
                }`}>
                  L{p.level}
                </span>
                <span className="text-[11px] text-dark-text-primary font-medium flex-1">
                  {p.skill_name}
                </span>
                <span className="text-[10px] text-dark-text-secondary font-mono">
                  pri: {(p.priority * 100).toFixed(0)}%
                </span>
              </div>
              <p className="text-[10px] text-dark-text-secondary">{p.reason}</p>
              <span className="text-[9px] text-dark-text-secondary/40 mt-1">
                {TYPE_LABELS[p.skill_type] || p.skill_type}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
