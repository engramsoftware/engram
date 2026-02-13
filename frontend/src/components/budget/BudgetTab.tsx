/**
 * Budget tracking tab — spending overview with chart, category breakdown,
 * and expense list with add/delete functionality.
 *
 * Uses a simple bar chart rendered with CSS (no chart library dependency).
 * Fetches data from /api/budget endpoints.
 */

import { useState, useEffect, useCallback } from 'react'
import { Plus, Trash2, DollarSign, TrendingUp, TrendingDown, RefreshCw, PieChart } from 'lucide-react'

import { budgetApi } from '../../services/api'

interface Expense {
  id: string
  amount: number
  category: string
  description: string
  date: string
  store: string | null
  created_at: string
}

interface CategorySummary {
  category: string
  spent: number
  budget?: number
  remaining?: number
  percent_used?: number
}

interface Summary {
  period_days: number
  total_spent: number
  total_budget: number | null
  expense_count: number
  categories: CategorySummary[]
}

/** Color palette for categories. */
const CAT_COLORS: Record<string, string> = {
  groceries: '#22c55e',
  dining: '#f97316',
  transport: '#3b82f6',
  entertainment: '#a855f7',
  utilities: '#6b7280',
  shopping: '#ec4899',
  health: '#14b8a6',
  subscriptions: '#eab308',
  housing: '#8b5cf6',
  education: '#06b6d4',
  travel: '#f43f5e',
  other: '#94a3b8',
}

function getCatColor(cat: string): string {
  return CAT_COLORS[cat.toLowerCase()] || CAT_COLORS.other
}

export default function BudgetTab() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [expenses, setExpenses] = useState<Expense[]>([])
  const [loading, setLoading] = useState(true)
  const [days, setDays] = useState(30)

  // Add expense form
  const [showAdd, setShowAdd] = useState(false)
  const [addAmount, setAddAmount] = useState('')
  const [addCategory, setAddCategory] = useState('')
  const [addDesc, setAddDesc] = useState('')
  const [addStore, setAddStore] = useState('')

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [sum, exp] = await Promise.all([
        budgetApi.summary(days),
        budgetApi.list(days),
      ])
      setSummary(sum)
      setExpenses(exp)
    } catch (err) {
      console.error('Budget fetch failed:', err)
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => { refresh() }, [refresh])

  const handleAdd = async () => {
    const amt = parseFloat(addAmount)
    if (!amt || amt <= 0) return
    try {
      await budgetApi.add({
        amount: amt,
        category: addCategory || 'other',
        description: addDesc,
        store: addStore || undefined,
      })
      setAddAmount('')
      setAddCategory('')
      setAddDesc('')
      setAddStore('')
      setShowAdd(false)
      refresh()
    } catch (err) {
      console.error('Add expense failed:', err)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await budgetApi.delete(id)
      refresh()
    } catch (err) {
      console.error('Delete failed:', err)
    }
  }

  const maxCatSpent = summary?.categories.length
    ? Math.max(...summary.categories.map(c => c.spent))
    : 1

  return (
    <div className="h-full overflow-y-auto p-4 sm:p-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-green-500 to-emerald-600
                          flex items-center justify-center">
            <DollarSign size={20} className="text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-dark-text-primary">Budget</h1>
            <p className="text-xs text-dark-text-secondary">Track spending & set goals</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={e => setDays(Number(e.target.value))}
            className="bg-dark-bg-secondary border border-dark-border rounded-lg px-3 py-1.5
                       text-sm text-dark-text-primary"
          >
            <option value={7}>7 days</option>
            <option value={14}>14 days</option>
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
            <option value={365}>1 year</option>
          </select>
          <button
            onClick={refresh}
            className="p-2 rounded-lg text-dark-text-secondary hover:text-dark-text-primary
                       hover:bg-dark-bg-secondary transition-colors"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
          <button
            onClick={() => setShowAdd(!showAdd)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 hover:bg-green-700
                       text-white text-sm rounded-lg transition-colors"
          >
            <Plus size={14} />
            <span>Add</span>
          </button>
        </div>
      </div>

      {/* Add expense form */}
      {showAdd && (
        <div className="mb-6 p-4 bg-dark-bg-secondary border border-dark-border rounded-xl space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <input
              type="number"
              placeholder="Amount"
              value={addAmount}
              onChange={e => setAddAmount(e.target.value)}
              className="bg-dark-bg-primary border border-dark-border rounded-lg px-3 py-2
                         text-sm text-dark-text-primary placeholder-dark-text-secondary"
              step="0.01"
              min="0"
            />
            <input
              type="text"
              placeholder="Category (LLM sorts)"
              value={addCategory}
              onChange={e => setAddCategory(e.target.value)}
              className="bg-dark-bg-primary border border-dark-border rounded-lg px-3 py-2
                         text-sm text-dark-text-primary placeholder-dark-text-secondary"
            />
            <input
              type="text"
              placeholder="Description"
              value={addDesc}
              onChange={e => setAddDesc(e.target.value)}
              className="bg-dark-bg-primary border border-dark-border rounded-lg px-3 py-2
                         text-sm text-dark-text-primary placeholder-dark-text-secondary"
            />
            <input
              type="text"
              placeholder="Store (optional)"
              value={addStore}
              onChange={e => setAddStore(e.target.value)}
              className="bg-dark-bg-primary border border-dark-border rounded-lg px-3 py-2
                         text-sm text-dark-text-primary placeholder-dark-text-secondary"
            />
          </div>
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setShowAdd(false)}
              className="px-3 py-1.5 text-sm text-dark-text-secondary hover:text-dark-text-primary"
            >
              Cancel
            </button>
            <button
              onClick={handleAdd}
              disabled={!addAmount || parseFloat(addAmount) <= 0}
              className="px-4 py-1.5 bg-green-600 hover:bg-green-700 text-white text-sm
                         rounded-lg disabled:opacity-50 transition-colors"
            >
              Add Expense
            </button>
          </div>
        </div>
      )}

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
          <div className="bg-dark-bg-secondary border border-dark-border rounded-xl p-4">
            <div className="text-xs text-dark-text-secondary mb-1">Total Spent</div>
            <div className="text-2xl font-bold text-dark-text-primary">
              ${summary.total_spent.toFixed(2)}
            </div>
          </div>
          <div className="bg-dark-bg-secondary border border-dark-border rounded-xl p-4">
            <div className="text-xs text-dark-text-secondary mb-1">Expenses</div>
            <div className="text-2xl font-bold text-dark-text-primary">{summary.expense_count}</div>
          </div>
          <div className="bg-dark-bg-secondary border border-dark-border rounded-xl p-4">
            <div className="text-xs text-dark-text-secondary mb-1">Categories</div>
            <div className="text-2xl font-bold text-dark-text-primary">
              {summary.categories.length}
            </div>
          </div>
          <div className="bg-dark-bg-secondary border border-dark-border rounded-xl p-4">
            <div className="text-xs text-dark-text-secondary mb-1">Avg / Day</div>
            <div className="text-2xl font-bold text-dark-text-primary">
              ${summary.total_spent > 0
                ? (summary.total_spent / summary.period_days).toFixed(2)
                : '0.00'}
            </div>
          </div>
        </div>
      )}

      {/* Category breakdown chart */}
      {summary && summary.categories.length > 0 && (
        <div className="bg-dark-bg-secondary border border-dark-border rounded-xl p-4 mb-6">
          <div className="flex items-center gap-2 mb-4">
            <PieChart size={16} className="text-dark-text-secondary" />
            <h2 className="text-sm font-semibold text-dark-text-primary">Spending by Category</h2>
          </div>
          <div className="space-y-3">
            {summary.categories.map(cat => (
              <div key={cat.category}>
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <div
                      className="w-3 h-3 rounded-full"
                      style={{ backgroundColor: getCatColor(cat.category) }}
                    />
                    <span className="text-sm text-dark-text-primary capitalize">{cat.category}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-mono text-dark-text-primary">
                      ${cat.spent.toFixed(2)}
                    </span>
                    {summary.total_spent > 0 && (
                      <span className="text-xs text-dark-text-secondary">
                        {((cat.spent / summary.total_spent) * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                </div>
                {/* Bar */}
                <div className="h-2.5 bg-dark-bg-primary rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${(cat.spent / maxCatSpent) * 100}%`,
                      backgroundColor: getCatColor(cat.category),
                    }}
                  />
                </div>
                {cat.budget !== undefined && (
                  <div className="flex items-center gap-1 mt-0.5">
                    {(cat.remaining ?? 0) >= 0 ? (
                      <TrendingDown size={10} className="text-green-400" />
                    ) : (
                      <TrendingUp size={10} className="text-red-400" />
                    )}
                    <span className={`text-[10px] ${(cat.remaining ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {(cat.remaining ?? 0) >= 0
                        ? `$${cat.remaining?.toFixed(2)} under budget`
                        : `$${Math.abs(cat.remaining ?? 0).toFixed(2)} over budget`}
                    </span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Expense list */}
      <div className="bg-dark-bg-secondary border border-dark-border rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-dark-border">
          <h2 className="text-sm font-semibold text-dark-text-primary">Recent Expenses</h2>
        </div>
        {expenses.length === 0 ? (
          <div className="px-4 py-8 text-center text-dark-text-secondary text-sm">
            No expenses yet. Add one above or use <code>/budget add $50 groceries</code> in chat.
          </div>
        ) : (
          <div className="divide-y divide-dark-border">
            {expenses.map(exp => (
              <div
                key={exp.id}
                className="flex items-center gap-3 px-4 py-3 hover:bg-dark-bg-primary/50 transition-colors group"
              >
                <div
                  className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                  style={{ backgroundColor: getCatColor(exp.category) }}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-dark-text-primary">
                      ${exp.amount.toFixed(2)}
                    </span>
                    <span className="text-xs text-dark-text-secondary capitalize px-1.5 py-0.5
                                     bg-dark-bg-primary rounded">
                      {exp.category}
                    </span>
                  </div>
                  {(exp.description || exp.store) && (
                    <div className="text-xs text-dark-text-secondary truncate mt-0.5">
                      {exp.description}{exp.store ? ` · ${exp.store}` : ''}
                    </div>
                  )}
                </div>
                <div className="text-xs text-dark-text-secondary flex-shrink-0">
                  {new Date(exp.date).toLocaleDateString()}
                </div>
                <button
                  onClick={() => handleDelete(exp.id)}
                  className="p-1 text-dark-text-secondary hover:text-red-400
                             opacity-0 group-hover:opacity-100 transition-all"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
